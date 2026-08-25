"""Injeção da conexão com o banco.

Uma conexão por requisição: conexões SQLite não atravessam threads com
segurança, e o FastAPI executa endpoint síncrono num pool de threads. Abrir e
fechar é barato o bastante nesta escala.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fluxo.persistencia import repositorio


def obter_conexao() -> Iterator[sqlite3.Connection]:
    conn = repositorio.conectar()
    try:
        yield conn
    finally:
        conn.close()
