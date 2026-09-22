"""Clipes de dúvida: a caixa-preta dos momentos em que a contagem pode ter errado.

Três coisas disparam um clipe:
  * um track que sumiu perto da linha sem cruzar (a linha mesma acusa, em
    `LinhaDeContagem.duvidas`);
  * uma detecção fraca perto da linha (a pessoa que o YOLO quase não viu);
  * uma decisão de re-ID sem par, ou com similaridade no fio do limiar.

O clipe são os quadros ANOTADOS dos segundos antes e depois, num ZIP de JPEGs,
mais um JSON dizendo o que o sistema achou. Alguém julga na aba "Revisão" do
painel, quadro a quadro: acertou, errou, não sei. O veredito fica; o clipe some.

Por que ZIP e não mp4: o OpenCV empacotado não traz H.264 em toda máquina
(`Unable to create encoder`), e o que sobra — mp4v — nenhum navegador toca. O
ZIP não depende de codec nenhum, é stdlib, e para julgar "passaram duas juntas"
parar no quadro certo vale mais que ver rodar.

LGPD (PROJETO §16.2): isto é imagem de pessoa real. Mesmo regime de
`--guardar-recortes` — desligado por padrão, só em validação, disco local,
apagado em 48 h ou no veredito, o que vier antes. Nunca vai ao banco nem à
API.

O anel guarda JPEG (bytes), não arrays: 180 quadros VGA em JPEG são ~7 MB;
crus seriam 160 MB. E, como já são JPEG, gravar é só zipar. O cv2 entra apenas
na codificação, para o gatilho, o anel e a purga rodarem nos testes de núcleo.
"""

from __future__ import annotations

import csv
import json
import threading
import time
import zipfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fluxo.contagem import geometria
from fluxo.contagem.linha import Duvida, LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.dominio.rastro import Rastro

GATILHO_CONTAGEM = "contagem"
GATILHO_DETECCAO = "deteccao"
GATILHO_REID = "reid"
# Quando várias dúvidas caem no mesmo quadro, só uma vira clipe. Contagem vem
# primeiro porque é a que descreve um evento que NÃO existe — a pessoa que o
# sistema perdeu; detecção fraca é a mais comum e a menos conclusiva.
PRIORIDADE = {GATILHO_CONTAGEM: 0, GATILHO_REID: 1, GATILHO_DETECCAO: 2}

# Qualidade do JPEG no anel. 60 em vez de 70 corta ~30% do clipe (medido:
# 7,6 MB -> ~5 MB em 768x576/12 s) sem atrapalhar quem está julgando.
QUALIDADE_JPEG = 60

# Detecção abaixo disto, perto da linha, é dúvida: o detector viu alguma
# coisa, mas não tinha certeza de que era gente.
CONFIANCA_DUVIDA = 0.5
# Similaridade a menos disto do limiar (para cima ou para baixo) é decisão no
# fio da navalha — o caso em que o limiar, e não a pessoa, decidiu.
MARGEM_SIMILARIDADE = 0.05

# Teto de clipes por execução. Medido: ~2,5 MB cada em 768x576/12 s, então 200
# são ~500 MB. Sem teto, uma câmera ruim gravando uma dúvida a cada 10 s enche
# o disco num dia — e ninguém julga 8 mil clipes.
MAXIMO_POR_EXECUCAO = 200

VEREDITOS = ("acertou", "errou", "nao_sei")
ARQUIVO_VEREDITOS = "vereditos.csv"
COLUNAS_VEREDITOS = ["id_clipe", "instante", "camera", "gatilho", "veredito", "nota", "julgado_em"]


# --------------------------------------------------------------------------
# Gatilhos
# --------------------------------------------------------------------------


def duvidas_de_deteccao(rastros: list[Rastro], linha: LinhaDeContagem) -> list[Duvida]:
    """Detecção fraca a menos de `raio_duvida` da linha."""
    duvidas = []
    for r in rastros:
        if r.confianca >= CONFIANCA_DUVIDA:
            continue
        d = geometria.distancia_ponto_reta(r.ponto_base, linha.a, linha.b)
        if d <= linha.raio_duvida:
            duvidas.append(Duvida(
                GATILHO_DETECCAO, r.id_local,
                f"track {r.id_local} com confiança {r.confianca:.2f} a {d:.0f} px da linha",
            ))
    return duvidas


def duvidas_de_reid(decisoes, limiares: dict[str, float]) -> list[Duvida]:
    """Saída sem par, ou decisão a menos de MARGEM_SIMILARIDADE do limiar.

    `limiares` mapeia método ("saida", "reentrada") ao limiar em vigor; vazio
    quando o agente roda sem --identificar.
    """
    duvidas = []
    for d in decisoes:
        if d.metodo == "nao_atribuido":
            limiar = limiares.get("saida")
            if d.similaridade is None:
                melhor = "ninguém dentro para comparar"
            elif limiar is not None and d.similaridade >= limiar:
                # Passa do limiar e mesmo assim ficou sem par: a candidata foi
                # dada a outra saída do mesmo lote. Dizer "0.95 < 0.70" aqui
                # seria mentira, e é justamente o caso interessante.
                melhor = (
                    f"melhor sim {d.similaridade:.2f} passava do limiar "
                    f"{limiar:.2f}, mas a candidata foi par de outra saída"
                )
            else:
                melhor = (
                    f"melhor sim {d.similaridade:.2f} < {limiar:.2f}"
                    if limiar is not None else f"melhor sim {d.similaridade:.2f}"
                )
            duvidas.append(Duvida(
                GATILHO_REID, d.id_local, f"saída t{d.id_local} sem par ({melhor})",
            ))
            continue
        limiar = limiares.get(d.metodo)
        if limiar is None or d.similaridade is None:
            continue
        if abs(d.similaridade - limiar) <= MARGEM_SIMILARIDADE:
            duvidas.append(Duvida(
                GATILHO_REID, d.id_local,
                f"{d.metodo} t{d.id_local} → {d.pseudonimo} com sim {d.similaridade:.2f} "
                f"no fio do limiar {limiar:.2f}",
            ))
    return duvidas


# --------------------------------------------------------------------------
# Gravador
# --------------------------------------------------------------------------


def _codificar_jpg(imagem, qualidade: int = QUALIDADE_JPEG) -> bytes:
    import cv2

    ok, dados = cv2.imencode(".jpg", imagem, [int(cv2.IMWRITE_JPEG_QUALITY), qualidade])
    if not ok:
        raise ValueError("cv2.imencode falhou")
    return dados.tobytes()


def _gravar_zip(caminho: Path, quadros: list[bytes], sidecar: dict) -> None:
    """Zipa os JPEGs do anel e escreve o JSON ao lado. Roda numa thread própria.

    ZIP_STORED, não DEFLATE: JPEG já está comprimido, e comprimir de novo
    gasta CPU do agente para economizar uns 2%.
    """
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_STORED) as z:
        for i, jpg in enumerate(quadros):
            z.writestr(f"{i:04d}.jpg", jpg)
    caminho.with_suffix(".json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def abrir_clipe(caminho: Path) -> list[bytes]:
    """Os quadros de um clipe, em ordem. É o que a aba Revisão exibe."""
    with zipfile.ZipFile(caminho) as z:
        return [z.read(nome) for nome in sorted(z.namelist())]


def _gravar_em_thread(caminho: Path, quadros: list[bytes], sidecar: dict) -> list:
    """Grava fora do laço principal. Devolve a thread, para quem quiser esperar."""
    t = threading.Thread(
        target=_gravar_zip, args=(caminho, quadros, sidecar), daemon=True, name="clipe",
    )
    t.start()
    return [t]


@dataclass(slots=True)
class _Gravando:
    duvida: Duvida
    instante: datetime
    restantes: int


class GravadorDeDuvidas:
    """Anel de quadros anotados + gatilhos + debounce. Um por câmera."""

    def __init__(
        self,
        pasta: Path,
        camera_id: str,
        fps: float,
        largura: int,
        altura: int,
        params: dict | None = None,
        antes_s: float = 8.0,
        depois_s: float = 4.0,
        intervalo_min_s: float = 10.0,
        maximo: int = MAXIMO_POR_EXECUCAO,
        limiares: dict[str, float] | None = None,
        codificar: Callable[[object], bytes] | None = None,
        gravar: Callable[[Path, list[bytes], dict], None] | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pasta = Path(pasta)
        self.camera_id = camera_id
        self.fps = max(1.0, float(fps))
        self.largura, self.altura = int(largura), int(altura)
        self.params = params or {}
        self.depois_quadros = max(1, int(self.fps * depois_s))
        self.intervalo_min_s = intervalo_min_s
        self.maximo = maximo
        self.limiares = limiares or {}
        self._codificar = codificar or _codificar_jpg
        self._gravar = gravar or _gravar_em_thread
        self._relogio = relogio

        # (jpeg, instante): o instante mede o fps real na hora de gravar — a
        # FonteViva ainda não conhece a câmera quando isto é construído.
        self._anel: deque[tuple[bytes, datetime]] = deque(
            maxlen=max(2, int(self.fps * (antes_s + depois_s)))
        )
        self._em_curso: _Gravando | None = None
        self._threads: list = []
        # Um intervalo POR GATILHO: numa cena cheia a detecção fraca dispara
        # toda hora, e um relógio só faria ela engolir a vaga da contagem —
        # que é a dúvida que interessa e nasce segundos depois do sumiço.
        self._ultimo_em: dict[str, float] = {}
        # ponytail: O(n) num deque de 500 chaves; vira dict se um dia doer.
        self._vistas: deque[tuple[str, int | None]] = deque(maxlen=500)

        self.gravados = 0
        self.ignoradas = 0

    def observar(
        self, imagem_anotada, instante: datetime, rastros, linha, decisoes
    ) -> Duvida | None:
        """Um quadro anotado por vez. Devolve a dúvida que começou a gravar, se houver."""
        self._anel.append((self._codificar(imagem_anotada), instante))
        if not self.largura or not self.altura:
            # Fonte viva só sabe o tamanho depois de conectar; o quadro sabe sempre.
            forma = getattr(imagem_anotada, "shape", None)
            if forma is not None and len(forma) >= 2:
                self.altura, self.largura = int(forma[0]), int(forma[1])

        if self._em_curso is not None:
            self._em_curso.restantes -= 1
            if self._em_curso.restantes <= 0:
                self._fechar()

        duvidas = list(linha.duvidas)
        linha.duvidas.clear()
        duvidas += duvidas_de_deteccao(rastros, linha)
        duvidas += duvidas_de_reid(decisoes, self.limiares)

        escolhida = None
        for d in sorted(duvidas, key=lambda d: PRIORIDADE.get(d.gatilho, 9)):
            chave = (d.gatilho, d.track)
            if chave in self._vistas:
                continue
            self._vistas.append(chave)
            if escolhida is None and self._pode_gravar(d.gatilho):
                escolhida = d
            else:
                self.ignoradas += 1

        if escolhida is not None:
            self._em_curso = _Gravando(escolhida, instante, self.depois_quadros)
            self._ultimo_em[escolhida.gatilho] = self._relogio()
        return escolhida

    def _pode_gravar(self, gatilho: str) -> bool:
        if self._em_curso is not None or self.gravados >= self.maximo:
            return False
        ultimo = self._ultimo_em.get(gatilho)
        return ultimo is None or self._relogio() - ultimo >= self.intervalo_min_s

    def _fechar(self) -> None:
        g, self._em_curso = self._em_curso, None
        assert g is not None
        d = g.duvida
        id_clipe = f"{g.instante:%Y%m%d_%H%M%S}_{d.gatilho}_t{d.track}"
        quadros = [jpg for jpg, _ in self._anel]
        duracao = (self._anel[-1][1] - self._anel[0][1]).total_seconds()
        fps = round((len(quadros) - 1) / duracao, 1) if duracao > 0 else self.fps
        sidecar = {
            "id": id_clipe,
            "instante": g.instante.isoformat(),
            "camera": self.camera_id,
            "gatilho": d.gatilho,
            "track": d.track,
            "motivo": d.motivo,
            "fps": fps,
            "largura": self.largura,
            "altura": self.altura,
            "quadros": len(self._anel),
            "params": self.params,
        }
        self.pasta.mkdir(parents=True, exist_ok=True)
        threads = self._gravar(self.pasta / f"{id_clipe}.zip", quadros, sidecar)
        if threads:
            self._threads.extend(threads)
        self.gravados += 1

    def fechar(self, espera_s: float = 30.0) -> None:
        """Fim da execução: grava o clipe em curso e espera os mp4 saírem.

        A espera não é cosmética: as threads são daemon, e sem ela o processo
        termina no meio da escrita — o clipe fica com 0 byte e sem sidecar.
        """
        if self._em_curso is not None:
            self._fechar()
        for t in self._threads:
            t.join(timeout=espera_s)
        self._threads.clear()


# --------------------------------------------------------------------------
# Disco: listar, julgar, purgar
# --------------------------------------------------------------------------


def listar_clipes(pasta: Path) -> list[dict]:
    """Os clipes pendentes de veredito, mais novo primeiro. Só os já gravados."""
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    clipes = []
    for sidecar in pasta.rglob("*.json"):
        quadros = sidecar.with_suffix(".zip")
        if not quadros.exists():
            continue
        try:
            dados = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dados["zip"] = str(quadros)
        dados["json"] = str(sidecar)
        clipes.append(dados)
    clipes.sort(key=lambda c: c.get("instante", ""), reverse=True)
    return clipes


def registrar_veredito(pasta: Path, clipe: dict, veredito: str, nota: str = "") -> None:
    """Uma linha no CSV, e o clipe some: o veredito fica, a imagem não."""
    if veredito not in VEREDITOS:
        raise ValueError(f"veredito inválido: {veredito!r}")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / ARQUIVO_VEREDITOS
    novo = not caminho.exists()
    with caminho.open("a", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        if novo:
            escritor.writerow(COLUNAS_VEREDITOS)
        escritor.writerow([
            clipe.get("id", ""), clipe.get("instante", ""), clipe.get("camera", ""),
            clipe.get("gatilho", ""), veredito, nota,
            datetime.now(FUSO_LOCAL).isoformat(),
        ])
    for chave in ("zip", "json"):
        arquivo = clipe.get(chave)
        if arquivo:
            Path(arquivo).unlink(missing_ok=True)


def purgar_clipes(pasta: Path, max_idade_h: float = 48.0, agora: float | None = None) -> int:
    """Apaga clipes mais velhos que `max_idade_h`. Devolve quantos arquivos."""
    pasta = Path(pasta)
    if not pasta.exists():
        return 0
    limite = (time.time() if agora is None else agora) - max_idade_h * 3600
    n = 0
    for arquivo in list(pasta.rglob("*.zip")) + list(pasta.rglob("*.json")):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink()
                n += 1
        except OSError:
            continue
    return n
