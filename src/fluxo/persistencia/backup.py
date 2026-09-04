"""Backup diário do banco.

Usa a API `Connection.backup` do sqlite3, que copia página a página de forma
consistente mesmo com o serviço escrevendo (WAL) — copiar o arquivo por fora
durante uma escrita produziria uma cópia corrompida de vez em quando, que é o
pior tipo de backup: o que falha só no dia em que é preciso.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

PREFIXO = "fluxo-"


def nome_do_dia(dia: date) -> str:
    return f"{PREFIXO}{dia.isoformat()}.db"


def fazer_backup(origem: Path, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(str(origem))
    try:
        alvo = sqlite3.connect(str(destino))
        try:
            conexao.backup(alvo)
        finally:
            alvo.close()
    finally:
        conexao.close()
    return destino


def podar_antigos(pasta: Path, reter_dias: int = 14, hoje: date | None = None) -> list[Path]:
    """Apaga backups além da retenção. Devolve o que apagou."""
    hoje = hoje or date.today()
    apagados: list[Path] = []
    for arquivo in sorted(pasta.glob(f"{PREFIXO}*.db")):
        try:
            dia = date.fromisoformat(arquivo.stem.removeprefix(PREFIXO))
        except ValueError:
            # Nome fora do padrão não é nosso para apagar — pode ser uma cópia
            # manual feita num susto, exatamente a que não se pode perder.
            continue
        if (hoje - dia).days > reter_dias:
            arquivo.unlink()
            apagados.append(arquivo)
    return apagados


def backup_diario(
    origem: Path, pasta: Path, reter_dias: int = 14, hoje: date | None = None
) -> Path | None:
    """Um backup por dia, idempotente: se o de hoje já existe, não refaz.

    Devolve o caminho criado, ou None quando não havia nada a fazer (backup
    do dia já existe, ou o banco ainda nem foi criado).
    """
    hoje = hoje or date.today()
    destino = pasta / nome_do_dia(hoje)
    if destino.exists() or not Path(origem).exists():
        return None
    criado = fazer_backup(Path(origem), destino)
    podar_antigos(pasta, reter_dias, hoje)
    return criado
