"""O último quadro anotado, num arquivo, para a aba "Ao vivo" do painel.

A câmera atende um cliente por vez, e esse cliente é o agente: ninguém mais
consegue abrir o stream para ver a porta. Então o agente republica o que já
processa — o quadro com as caixas e a linha — num único JPEG por câmera,
sobrescrito até 5 vezes por segundo. É um espelho, não uma gravação: o
arquivo de agora apaga o de antes, e nada se acumula.

A escrita é atômica (arquivo temporário + `os.replace`): quem lê nunca vê um
JPEG pela metade. O cv2 só é importado na codificação, para o módulo continuar
importável — e testável — no ambiente de núcleo.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path


class PublicadorDeQuadro:
    def __init__(
        self,
        caminho: Path,
        intervalo_s: float = 0.2,
        qualidade: int = 70,
        codificar: Callable[[object], bytes] | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.caminho = caminho
        self.intervalo_s = intervalo_s
        self.qualidade = qualidade
        self._codificar = codificar or self._codificar_jpeg
        self._relogio = relogio
        self._ultimo: float | None = None
        self.publicados = 0
        self.falhas = 0

    def _codificar_jpeg(self, imagem) -> bytes:
        import cv2

        ok, dados = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, self.qualidade])
        if not ok:
            raise ValueError("cv2.imencode recusou o quadro")
        return dados.tobytes()

    def publicar(self, imagem) -> bool:
        """Grava se já passou o intervalo. Devolve True quando gravou."""
        agora = self._relogio()
        if self._ultimo is not None and agora - self._ultimo < self.intervalo_s:
            return False
        self._ultimo = agora
        try:
            dados = self._codificar(imagem)
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.caminho.with_suffix(".tmp")
            temporario.write_bytes(dados)
            os.replace(temporario, self.caminho)
        except (OSError, ValueError):
            # Disco cheio ou pasta sumida não podem derrubar a contagem; o
            # painel mostra "sem quadro" e a operação segue.
            self.falhas += 1
            return False
        self.publicados += 1
        return True


def idade_do_quadro(caminho: Path, agora: float | None = None) -> float | None:
    """Segundos desde a última gravação, ou None se não há quadro."""
    try:
        modificado = caminho.stat().st_mtime
    except OSError:
        return None
    agora = time.time() if agora is None else agora
    return max(0.0, agora - modificado)
