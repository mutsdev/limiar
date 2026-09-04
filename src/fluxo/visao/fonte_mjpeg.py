"""Lê MJPEG multipart direto do HTTP, sem passar pelo `cv2.VideoCapture`.

Medido contra a câmera real (XIAO ESP32S3, 01/09/2026): o `VideoCapture`
entregou **1,1 quadro/s** de um stream que o `curl` baixava a 16 — e ainda
estourou `Unknown C++ exception from OpenCV code`. O backend FFmpeg trata o
`multipart/x-mixed-replace` como um contêiner de vídeo qualquer, com buffer e
heurística de sincronismo que não fazem sentido para uma sequência de JPEGs
independentes.

Aqui o trabalho é o que realmente precisa ser feito: achar o `Content-Length`,
recortar exatamente aqueles bytes, e decodificar. A separação dos quadros é
função pura (`separar_quadros`), testável sem rede e sem OpenCV.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime

import httpx

from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.visao.fonte import Quadro

# O ESP32 manda `Content-Length` em cada parte, e é nele que dá para confiar:
# procurar o delimitador dentro do JPEG acharia a sequência por acaso, porque
# dado binário contém qualquer coisa.
#
# O tamanho e o fim do cabeçalho são procurados em separado porque
# `Content-Length` NÃO é o último campo: o firmware manda `X-Timestamp` depois
# dele (`app_httpd.cpp:98` do CameraWebServer). Exigir `\r\n\r\n` colado ao
# número fez a leitura devolver zero quadro — conectava, e nada chegava.
_TAMANHO = re.compile(rb"Content-Length:\s*(\d+)", re.IGNORECASE)
FIM_CABECALHO = b"\r\n\r\n"

# Sem teto, um servidor que mande cabeçalho sem corpo faria o buffer crescer
# até o processo morrer — numa operação de meses isso acontece.
LIMITE_BUFFER = 8 * 1024 * 1024


def separar_quadros(pedacos: Iterable[bytes]) -> Iterator[bytes]:
    """Converte a corrente de bytes do multipart em JPEGs, um por vez."""
    buffer = b""
    faltam: int | None = None

    for pedaco in pedacos:
        buffer += pedaco
        while True:
            if faltam is None:
                achado = _TAMANHO.search(buffer)
                fim = (
                    -1 if achado is None
                    else buffer.find(FIM_CABECALHO, achado.end())
                )
                if fim == -1:
                    if len(buffer) > LIMITE_BUFFER:
                        raise ValueError(
                            "Mais de 8 MB sem um cabeçalho completo: isto não é MJPEG."
                        )
                    break
                faltam = int(achado.group(1))
                buffer = buffer[fim + len(FIM_CABECALHO):]
            if len(buffer) < faltam:
                break
            yield buffer[:faltam]
            buffer = buffer[faltam:]
            faltam = None


def _decodificar_com_cv2(jpeg: bytes):
    import cv2
    import numpy as np

    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def parece_mjpeg(url: str, timeout: float = 5.0) -> bool:
    """O que está nesta URL é um MJPEG multipart?

    Custa uma conexão, então quem chama deve lembrar que a placa costuma
    aceitar **um cliente por vez** — a conexão é fechada logo após o cabeçalho.
    """
    try:
        with httpx.stream("GET", url, timeout=timeout) as r:
            return "multipart/x-mixed-replace" in r.headers.get("content-type", "")
    except httpx.HTTPError:
        return False


class FonteMjpeg:
    """Mesma interface iteradora de `FonteDeVideo`, para stream MJPEG."""

    def __init__(
        self,
        url: str,
        timeout: float = 15.0,
        tamanho_pedaco: int = 8192,
        decodificador: Callable[[bytes], object] | None = None,
        registrador: logging.Logger | None = None,
    ) -> None:
        self.origem = url
        self.ao_vivo = True
        self.total_quadros = 0
        self.largura = 0
        self.altura = 0
        # Só se sabe a taxa medindo; 10 é o mínimo que o contrato pede e serve
        # de palpite até o primeiro segundo de vídeo passar.
        self.fps = 10.0
        self.corrompidos = 0

        self._decodificar = decodificador or _decodificar_com_cv2
        self._log = registrador or logging.getLogger(__name__)
        self._tamanho_pedaco = tamanho_pedaco
        self._fechado = threading.Event()

        self._cliente = httpx.Client(timeout=timeout)
        try:
            self._contexto = self._cliente.stream("GET", url)
            self._resposta = self._contexto.__enter__()
            self._resposta.raise_for_status()
        except Exception:
            self._cliente.close()
            raise

        tipo = self._resposta.headers.get("content-type", "")
        if "multipart" not in tipo:
            self.fechar()
            raise ValueError(f"{url} não é multipart (content-type: {tipo!r})")

    def __iter__(self) -> Iterator[Quadro]:
        indice = 0
        for jpeg in separar_quadros(self._resposta.iter_bytes(self._tamanho_pedaco)):
            if self._fechado.is_set():
                return
            imagem = self._decodificar(jpeg)
            if imagem is None:
                # Um JPEG truncado por perda de pacote não justifica derrubar a
                # conexão: o próximo quadro chega em 100 ms.
                self.corrompidos += 1
                continue
            if not self.largura:
                forma = getattr(imagem, "shape", None)
                if forma is not None and len(forma) >= 2:
                    self.altura, self.largura = int(forma[0]), int(forma[1])
            yield Quadro(indice, datetime.now(FUSO_LOCAL), imagem)
            indice += 1

    def fechar(self) -> None:
        self._fechado.set()
        try:
            self._contexto.__exit__(None, None, None)
        except Exception:
            pass
        self._cliente.close()

    def __enter__(self) -> FonteMjpeg:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def __repr__(self) -> str:
        return f"FonteMjpeg({self.origem!r}, {self.largura}x{self.altura})"
