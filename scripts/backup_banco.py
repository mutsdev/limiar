"""Copia o banco para a pasta de backups. Um por dia; reexecutar é inócuo.

    python scripts/backup_banco.py

O supervisor (rodar_tudo.py) chama isto sozinho uma vez por dia. O script
existe para rodar à mão — antes de mexer no banco, por exemplo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import garantir_venv

garantir_venv(exigir_visao=False)

from fluxo import config
from fluxo.persistencia import backup


def main() -> None:
    config.garantir_pastas()
    criado = backup.backup_diario(config.CAMINHO_BANCO, config.CAMINHO_BACKUPS)
    if criado is None:
        print(f"Nada a fazer: backup de hoje já existe (ou não há banco) em "
              f"{config.CAMINHO_BACKUPS}")
    else:
        print(f"Backup: {criado}")


if __name__ == "__main__":
    main()
