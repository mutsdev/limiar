"""Sobe o painel web.

    python scripts/rodar_painel.py
"""

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAINEL = RAIZ / "src" / "fluxo" / "analise" / "painel.py"


def main() -> None:
    # O streamlit executa o arquivo como script solto, não como módulo do
    # pacote — por isso o painel ajusta o sys.path por conta própria.
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(PAINEL),
         "--server.address", "127.0.0.1", "--server.port", "8501"],
        cwd=RAIZ,
        check=False,
    )


if __name__ == "__main__":
    main()
