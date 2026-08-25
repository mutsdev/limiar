"""Sobe o serviço central.

    python scripts/rodar_servico.py

Documentação interativa em http://127.0.0.1:8000/docs
"""

import argparse
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# O uvicorn com --recarregar sobe um processo filho, que não herda o sys.path
# ajustado acima — só o ambiente. Daí a variável.
os.environ["PYTHONPATH"] = os.pathsep.join(
    filter(None, [str(SRC), os.environ.get("PYTHONPATH", "")])
)

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(description="Serviço central do Limiar")
    # 0.0.0.0 é o que permite que o agente na portaria alcance o serviço.
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--recarregar", action="store_true")
    args = p.parse_args()

    uvicorn.run(
        "fluxo.servico.api:app", host=args.host, port=args.porta, reload=args.recarregar
    )


if __name__ == "__main__":
    main()
