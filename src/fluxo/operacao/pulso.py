"""Pulso de vida do agente: um arquivo cuja data de modificação diz "estou aqui".

O supervisor vê processo morto pelo `poll()`, mas não vê processo travado —
um agente preso numa inferência, ou num `read()` que nunca volta, fica vivo
para o sistema operacional e morto para a contagem. O pulso fecha esse
buraco: o agente bate a cada poucos segundos, e o supervisor confere a idade.

Bate-se do lado do consumidor da fonte (a volta do `for quadro in fonte`),
com quadro ou sem: câmera fora do ar continua batendo, porque o laço acorda no
timeout do watchdog; inferência travada para de bater, porque o laço não volta.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fluxo import config


def arquivo_do_agente(camera: str) -> Path:
    """Onde o agente daquela câmera bate. Um lugar só, para os dois lados."""
    return config.CAMINHO_LOGS / f"agente_{camera}.pulso"


class Pulso:
    def __init__(
        self, arquivo: Path, a_cada_s: float = 5.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.arquivo = arquivo
        self.a_cada_s = a_cada_s
        self._relogio = relogio
        self._ultimo: float | None = None
        self.batidas = 0

    def bater(self) -> None:
        """Atualiza a data do arquivo, no máximo uma vez a cada `a_cada_s`."""
        agora = self._relogio()
        if self._ultimo is not None and agora - self._ultimo < self.a_cada_s:
            return
        self._ultimo = agora
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.touch()
            self.batidas += 1
        except OSError:
            # Disco cheio ou pasta removida não podem derrubar a contagem.
            pass


def pulso_recente(arquivo: Path, maximo_s: float, agora: float | None = None) -> bool:
    """O arquivo foi tocado há menos de `maximo_s`? Sem arquivo é "não"."""
    try:
        modificado = arquivo.stat().st_mtime
    except OSError:
        return False
    agora = time.time() if agora is None else agora
    return agora - modificado <= maximo_s
