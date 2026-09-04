"""Impede a máquina de dormir enquanto o supervisor vive.

O padrão do Windows suspende em 30 minutos sem uso, e leva o agente junto.
Mudar a política de energia pode exigir admin; `SetThreadExecutionState` não
exige nada — é o mesmo mecanismo que um player de vídeo usa — e vale enquanto
a thread que chamou existir. O supervisor chama uma vez, no início, e depois
passa o resto da vida no laço da mesma thread.

Não cobre tampa de notebook fechada nem hibernação forçada por política de
domínio: isso continua sendo pedido ao TI (docs/operacao.md).
"""

from __future__ import annotations

import os

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def manter_acordado() -> bool:
    """Devolve True se o pedido foi aceito. Em outro sistema, ou sem a API, False."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        anterior = ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
        return bool(anterior)
    except Exception:
        return False


def comandos_powercfg() -> list[list[str]]:
    """Os ajustes de energia que o instalador tenta; podem exigir admin."""
    return [
        ["powercfg", "/change", "standby-timeout-ac", "0"],
        ["powercfg", "/change", "hibernate-timeout-ac", "0"],
    ]
