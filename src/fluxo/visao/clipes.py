"""Clipes de dúvida: a caixa-preta dos momentos em que a contagem pode ter errado.

Três coisas disparam um clipe:
  * um track que sumiu perto da linha sem cruzar (a linha mesma acusa, em
    `LinhaDeContagem.duvidas`);
  * uma detecção fraca perto da linha (a pessoa que o YOLO quase não viu);
  * uma decisão de re-ID sem par, ou com similaridade no fio do limiar.

O clipe é o vídeo ANOTADO dos segundos antes e depois, mais um JSON dizendo
o que o sistema achou. Alguém julga na aba "Revisão" do painel: acertou,
errou, não sei. O veredito fica; o clipe some.

LGPD (PROJETO §16.2): isto é imagem de pessoa real. Mesmo regime de
`--guardar-recortes` — desligado por padrão, só em validação, disco local,
apagado em 48 h ou no veredito, o que vier antes. Nunca vai ao banco nem à
API.

O anel guarda JPEG (bytes), não arrays: 180 quadros VGA em JPEG são ~7 MB;
crus seriam 160 MB. O cv2 só entra na codificação e na gravação, para o
gatilho, o anel e a purga rodarem nos testes de núcleo.
"""

from __future__ import annotations

import csv
import json
import threading
import time
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

# Detecção abaixo disto, perto da linha, é dúvida: o detector viu alguma
# coisa, mas não tinha certeza de que era gente.
CONFIANCA_DUVIDA = 0.5
# Similaridade a menos disto do limiar (para cima ou para baixo) é decisão no
# fio da navalha — o caso em que o limiar, e não a pessoa, decidiu.
MARGEM_SIMILARIDADE = 0.05

# Teto de clipes por execução. Medido: ~6 MB cada em 768x576/12 s, então 200
# são ~1,2 GB. Sem teto, uma câmera ruim gravando uma dúvida a cada 10 s
# enche 50 GB num dia — e ninguém julga 8 mil clipes.
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
            melhor = (
                f"melhor sim {d.similaridade:.2f} < {limiares.get('saida', 0):.2f}"
                if d.similaridade is not None else "ninguém dentro para comparar"
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


def _codificar_jpg(imagem, qualidade: int = 70) -> bytes:
    import cv2

    ok, dados = cv2.imencode(".jpg", imagem, [int(cv2.IMWRITE_JPEG_QUALITY), qualidade])
    if not ok:
        raise ValueError("cv2.imencode falhou")
    return dados.tobytes()


def _gravar_mp4(caminho: Path, quadros: list[bytes], sidecar: dict) -> None:
    """Decodifica o anel e escreve o mp4 + o JSON. Roda numa thread própria."""
    import cv2
    import numpy as np

    from fluxo.visao.anotador import GravadorDeVideo

    largura, altura, fps = sidecar["largura"], sidecar["altura"], sidecar["fps"]
    # avc1 (H.264) é o que o navegador toca; nem todo OpenCV tem o codec, e
    # aí mp4v grava igual — só que a aba Revisão passa a oferecer download.
    try:
        gravador = GravadorDeVideo(caminho, largura, altura, fps, fourcc="avc1")
        sidecar["codec"] = "avc1"
    except OSError:
        gravador = GravadorDeVideo(caminho, largura, altura, fps, fourcc="mp4v")
        sidecar["codec"] = "mp4v"
    with gravador:
        for jpg in quadros:
            imagem = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if imagem is not None:
                gravador.escrever(imagem)
    caminho.with_suffix(".json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _gravar_em_thread(caminho: Path, quadros: list[bytes], sidecar: dict) -> list:
    """Grava fora do laço principal. Devolve a thread, para quem quiser esperar."""
    t = threading.Thread(
        target=_gravar_mp4, args=(caminho, quadros, sidecar), daemon=True, name="clipe",
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
        self._ultimo_em: float | None = None
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
        for d in duvidas:
            chave = (d.gatilho, d.track)
            if chave in self._vistas:
                continue
            self._vistas.append(chave)
            if escolhida is None and self._pode_gravar():
                escolhida = d
            else:
                self.ignoradas += 1

        if escolhida is not None:
            self._em_curso = _Gravando(escolhida, instante, self.depois_quadros)
            self._ultimo_em = self._relogio()
        return escolhida

    def _pode_gravar(self) -> bool:
        if self._em_curso is not None or self.gravados >= self.maximo:
            return False
        agora = self._relogio()
        return self._ultimo_em is None or agora - self._ultimo_em >= self.intervalo_min_s

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
        threads = self._gravar(self.pasta / f"{id_clipe}.mp4", quadros, sidecar)
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
    """Os clipes pendentes de veredito, mais novo primeiro. Só os que já têm mp4."""
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    clipes = []
    for sidecar in pasta.rglob("*.json"):
        mp4 = sidecar.with_suffix(".mp4")
        if not mp4.exists():
            continue
        try:
            dados = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dados["mp4"] = str(mp4)
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
    for chave in ("mp4", "json"):
        arquivo = clipe.get(chave)
        if arquivo:
            Path(arquivo).unlink(missing_ok=True)


def purgar_clipes(pasta: Path, max_idade_h: float = 48.0, agora: float | None = None) -> int:
    """Apaga clipes mais velhos que `max_idade_h`. Devolve quantos."""
    pasta = Path(pasta)
    if not pasta.exists():
        return 0
    limite = (time.time() if agora is None else agora) - max_idade_h * 3600
    n = 0
    for arquivo in list(pasta.rglob("*.mp4")) + list(pasta.rglob("*.json")):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink()
                n += 1
        except OSError:
            continue
    return n
