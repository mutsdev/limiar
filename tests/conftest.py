"""Fixtures compartilhadas.

Todo teste roda contra um banco temporário. Nenhum teste toca o banco real —
se tocasse, uma execução de teste envenenaria a série histórica.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from fluxo import config
from fluxo.persistencia import repositorio

CAMERAS_TESTE = [
    ("entrada_a", "Entrada Principal", "Portaria da frente"),
    ("entrada_b", "Entrada Lateral", "Estacionamento"),
]


@pytest.fixture
def banco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """Banco temporário, com as duas câmeras cadastradas."""
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(config, "CAMINHO_BANCO", caminho)
    # O .env de quem desenvolve não pode mudar o resultado dos testes: sem
    # senha no painel, e o quadro ao vivo numa pasta vazia.
    monkeypatch.setattr(config, "SENHA_PAINEL", "")
    monkeypatch.setattr(config, "CAMINHO_QUADROS", tmp_path / "quadros")

    conn = repositorio.conectar(caminho)
    repositorio.criar_banco(conn)
    for id_, nome, local in CAMERAS_TESTE:
        repositorio.inserir_camera(conn, id_, nome, local)
    try:
        yield conn
    finally:
        conn.close()
