"""Grava os rastros de uma execução para reprocessar depois, sem GPU.

Rodar o YOLO custa uma passada inteira de vídeo. Ajustar um parâmetro de
contagem e querer saber se melhorou custava, até aqui, outra passada — e é isso
que tornava a calibração cara e, na prática, feita no olho.

A trilha quebra esse acoplamento: a visão roda **uma vez** e deixa gravado o que
enxergou; a contagem roda quantas vezes for preciso em cima do mesmo arquivo.
Como o replay alimenta a MESMA `LinhaDeContagem`, com os mesmos limiares, a
diferença entre duas execuções isola exatamente o parâmetro que mudou — o mesmo
princípio de `ground_truth.contar_no_ground_truth`.

Este módulo não importa cv2 nem numpy: roda sem o extra `visao` instalado.

Formato (JSON Lines). Primeira linha é o cabeçalho; as demais, um quadro cada,
**inclusive os quadros vazios** — sem eles o replay não saberia quantos quadros
se passaram, e `quadros_ate_esquecer` mediria errado.

    {"formato": "trilha/2", "camera": "mot17_09", "fps": 30.0, ...}
    {"q": 1, "t": "2026-01-01T08:00:00-03:00", "r": [[7, 100.0, 200.0, 150.0, 400.0, 0.71]]}
    {"q": 1, "e": [[7, [0.012, -0.34, ...]]]}

A terceira forma é da Etapa 2: a assinatura de aparência do track 7, calculada
no quadro 1. É linha própria, e não campo do quadro, porque é escrita depois —
a contagem decide o cruzamento, e só então a rede roda. `trilha/1` (sem essas
linhas) continua sendo lida.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fluxo.dominio.rastro import Rastro

FORMATO = "trilha/2"
FORMATOS_ACEITOS = ("trilha/1", FORMATO)

# Casas decimais de cada componente da assinatura. Cinco bastam para o cosseno
# e cortam o arquivo pela metade em relação ao float completo.
CASAS_ASSINATURA = 5


class TrilhaInvalida(Exception):
    """O arquivo de trilha não está no formato esperado."""


@dataclass(slots=True)
class Trilha:
    """Uma execução de visão gravada, pronta para ser recontada."""

    cabecalho: dict = field(default_factory=dict)
    # (indice do quadro, instante, rastros daquele quadro)
    quadros: list[tuple[int, datetime, list[Rastro]]] = field(default_factory=list)
    # Etapa 2: id_local -> [(quadro, assinatura), ...] em ordem de gravação.
    assinaturas: dict[int, list[tuple[int, list[float]]]] = field(default_factory=dict)

    @property
    def total_quadros(self) -> int:
        return len(self.quadros)

    def assinatura_de(self, id_local: int, quadro: int) -> list[float] | None:
        """A assinatura mais recente do track até aquele quadro, ou None."""
        candidata = None
        for q, vetor in self.assinaturas.get(id_local, ()):
            if q > quadro:
                break
            candidata = vetor
        return candidata

    @property
    def pessoas(self) -> int:
        return len({r.id_local for _, _, rastros in self.quadros for r in rastros})

    def __str__(self) -> str:
        c = self.cabecalho
        return (
            f"{c.get('camera', '?')} — {self.total_quadros} quadros, "
            f"{self.pessoas} tracks, modelo {c.get('modelo', '?')}"
        )


class Gravador:
    """Escreve a trilha quadro a quadro, enquanto a execução acontece."""

    def __init__(self, caminho: str | Path, **cabecalho) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._arquivo = self.caminho.open("w", encoding="utf-8")
        self._escrever({"formato": FORMATO, **cabecalho})
        self.quadros = 0

    def _escrever(self, objeto: dict) -> None:
        self._arquivo.write(json.dumps(objeto, ensure_ascii=False) + "\n")

    def gravar(self, quadro: int, instante: datetime, rastros: list[Rastro]) -> None:
        self._escrever(
            {
                "q": quadro,
                "t": instante.isoformat(),
                # Lista posicional em vez de dicionário por rastro: numa hora de
                # vídeo a diferença de tamanho do arquivo é de megabytes.
                "r": [
                    [r.id_local, *(round(v, 1) for v in r.caixa), round(r.confianca, 3)]
                    for r in rastros
                ],
            }
        )
        self.quadros += 1

    def gravar_assinatura(self, quadro: int, id_local: int, assinatura: list[float]) -> None:
        """Etapa 2: a aparência de um track, no quadro em que ele cruzou."""
        self._escrever(
            {"q": quadro, "e": [[id_local, [round(x, CASAS_ASSINATURA) for x in assinatura]]]}
        )

    def fechar(self) -> None:
        self._arquivo.close()

    def __enter__(self) -> Gravador:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()


def carregar(caminho: str | Path) -> Trilha:
    """Lê uma trilha inteira para a memória.

    Cabe: uma hora de vídeo a 30 fps com 20 pessoas por quadro dá alguns
    milhões de rastros, e a varredura de parâmetros precisa reler a mesma
    trilha dezenas de vezes — reabrir o arquivo a cada combinação seria o novo
    gargalo.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise TrilhaInvalida(
            f"Não achei a trilha em {caminho}.\n"
            f"Grave antes: python scripts/processar_video.py <camera> --gravar-trilhas"
        )

    trilha = Trilha()
    for numero, texto in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(), start=1
    ):
        linha = texto.strip()
        if not linha:
            continue
        try:
            objeto = json.loads(linha)
        except json.JSONDecodeError as erro:
            raise TrilhaInvalida(f"{caminho}:{numero} não é JSON válido") from erro

        if numero == 1:
            if objeto.get("formato") not in FORMATOS_ACEITOS:
                raise TrilhaInvalida(
                    f"{caminho} não é uma trilha (formato "
                    f"{objeto.get('formato')!r}, esperado {FORMATO!r})"
                )
            trilha.cabecalho = objeto
            continue

        if "e" in objeto:
            for id_local, vetor in objeto["e"]:
                trilha.assinaturas.setdefault(int(id_local), []).append(
                    (int(objeto["q"]), [float(x) for x in vetor])
                )
            continue

        rastros = [
            Rastro(
                id_local=int(r[0]),
                caixa=(float(r[1]), float(r[2]), float(r[3]), float(r[4])),
                confianca=float(r[5]),
            )
            for r in objeto.get("r", [])
        ]
        trilha.quadros.append(
            (int(objeto["q"]), datetime.fromisoformat(objeto["t"]), rastros)
        )

    if not trilha.cabecalho:
        raise TrilhaInvalida(f"{caminho} está vazia.")
    return trilha


def contar(trilha: Trilha, linha) -> list:
    """Passa a trilha gravada pela linha de contagem e devolve os eventos.

    A linha chega zerada e sai com as contagens — a mesma que o agente usa ao
    vivo, sem nenhum caminho alternativo. Se houvesse um segundo contador só
    para o replay, o número medido aqui não diria nada sobre o de produção.
    """
    eventos = []
    for quadro, instante, rastros in trilha.quadros:
        eventos.extend(linha.processar(quadro, instante, rastros))
    return eventos


def cruzamentos_por_pessoa(eventos: list) -> float:
    """Quantos eventos cada track que cruzou gerou. O ideal é 1,00.

    Serve onde não há contagem manual: acima de 1 significa que a mesma pessoa
    foi contada mais de uma vez, e isso é visível sem referência nenhuma.
    """
    if not eventos:
        return 0.0
    return len(eventos) / len({e.track_id_local for e in eventos})
