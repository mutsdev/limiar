"""De onde os quadros vêm.

Arquivo de vídeo, webcam e stream RTSP/MJPEG entram pela mesma porta, porque
`cv2.VideoCapture` aceita os três. É essa indiferença que torna barata a troca
para a câmera real: muda a string da fonte no YAML, não o código.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from fluxo.dominio.evento import FUSO_LOCAL


@dataclass(frozen=True, slots=True)
class Quadro:
    indice: int
    instante: datetime
    imagem: object  # ndarray do OpenCV
    # Marcado pela FonteViva no primeiro quadro depois de uma queda longa de
    # stream: avisa o consumidor que o estado de rastreio ficou velho demais.
    apos_lacuna: bool = False


class FonteDeVideo:
    """Itera quadros com um instante associado a cada um.

    Para arquivo, o instante é derivado do FPS a partir de `instante_inicial` —
    assim um vídeo gravado ontem produz eventos com a hora de ontem. Para
    câmera ao vivo, é o relógio. Quem consome não distingue os dois casos.
    """

    def __init__(
        self,
        origem: str | int | Path,
        instante_inicial: datetime | None = None,
        tempo_real: bool = False,
        velocidade: float = 1.0,
        pular_quadros: int = 0,
    ) -> None:
        self.origem = origem
        self.ao_vivo = isinstance(origem, int) or str(origem).startswith(
            ("rtsp://", "http://", "https://")
        )
        self.instante_inicial = instante_inicial or datetime.now(FUSO_LOCAL)
        self.tempo_real = tempo_real
        self.velocidade = max(0.01, velocidade)
        self.pular_quadros = max(0, pular_quadros)

        self._cap = cv2.VideoCapture(origem if isinstance(origem, int) else str(origem))
        if not self._cap.isOpened():
            raise FileNotFoundError(f"Não consegui abrir a fonte de vídeo: {origem}")

        fps = self._cap.get(cv2.CAP_PROP_FPS)
        # Stream às vezes não informa FPS; 25 é o palpite seguro para vigilância.
        self.fps = fps if fps and fps > 0 else 25.0
        total = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.total_quadros = int(total) if total and total > 0 else 0
        self.largura = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.altura = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def __iter__(self) -> Iterator[Quadro]:
        indice = 0
        intervalo = 1.0 / (self.fps * self.velocidade)
        proximo = time.monotonic()

        while True:
            ok, imagem = self._cap.read()
            if not ok:
                break

            # Pular quadros divide o custo sem perder a passagem: a pessoa
            # continua sendo vista várias vezes atravessando a linha.
            if self.pular_quadros and indice % (self.pular_quadros + 1):
                indice += 1
                continue

            instante = (
                datetime.now(FUSO_LOCAL)
                if self.ao_vivo
                else self.instante_inicial + timedelta(seconds=indice / self.fps)
            )

            yield Quadro(indice, instante, imagem)
            indice += 1

            if self.tempo_real and not self.ao_vivo:
                proximo += intervalo
                atraso = proximo - time.monotonic()
                if atraso > 0:
                    time.sleep(atraso)

    def fechar(self) -> None:
        self._cap.release()

    def __enter__(self) -> FonteDeVideo:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def __repr__(self) -> str:
        return (
            f"FonteDeVideo({self.origem!r}, {self.largura}x{self.altura}, "
            f"{self.fps:.1f} fps, {self.total_quadros or '?'} quadros)"
        )
