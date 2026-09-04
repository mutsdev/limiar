"""Registro em arquivo com rotação diária.

O caminho 24h não tem terminal para ler: o que acontecer às 3h da manhã só
existe se estiver num arquivo. A rotação é diária, e não por tamanho, porque a
pergunta operacional é sempre "o que houve na terça?" — nunca "o que há nos
últimos 10 MB".
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)-7s %(name)s %(message)s"


def configurar(
    nome: str,
    arquivo: Path | None = None,
    nivel: int = logging.INFO,
    reter_dias: int = 14,
    console: bool = True,
) -> logging.Logger:
    """Devolve um logger nomeado com handlers de arquivo e/ou console.

    Idempotente por handler: chamar de novo com o mesmo destino não duplica —
    importa porque o laço do agente reconfigura após cada reinício interno.
    """
    logger = logging.getLogger(nome)
    logger.setLevel(nivel)
    # O root logger de quem importar este pacote não é problema nosso;
    # propagar duplicaria cada linha quando ele tiver handler próprio.
    logger.propagate = False

    if arquivo is not None:
        alvo = os.path.abspath(arquivo)
        Path(alvo).parent.mkdir(parents=True, exist_ok=True)
        ja_tem = any(getattr(h, "baseFilename", "") == alvo for h in logger.handlers)
        if not ja_tem:
            de_arquivo = TimedRotatingFileHandler(
                alvo,
                when="midnight",
                backupCount=reter_dias,
                encoding="utf-8",
                # Sem escrever nada, nem cria o arquivo — um logger configurado
                # "por via das dúvidas" não deixa lixo para trás.
                delay=True,
            )
            de_arquivo.setFormatter(logging.Formatter(FORMATO))
            logger.addHandler(de_arquivo)

    tem_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, TimedRotatingFileHandler)
        for h in logger.handlers
    )
    if console and not tem_console:
        de_console = logging.StreamHandler(sys.stderr)
        de_console.setFormatter(logging.Formatter(FORMATO))
        logger.addHandler(de_console)

    return logger
