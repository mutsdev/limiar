"""O relatório de um dia — ou de um período de teste — para levar à reunião.

    python scripts/relatorio_dia.py entrada_real                 # hoje
    python scripts/relatorio_dia.py entrada_real --data 2026-09-03
    python scripts/relatorio_dia.py --todas
    python scripts/relatorio_dia.py --periodo "Teste de campo 03/09"

Imprime no terminal e grava em dados/saidas/relatorio_<data>_<camera>.md
(ou relatorio_<periodo>.md). Só lê o banco: pode rodar com o agente de pé.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.analise import relatorio
from fluxo.persistencia import repositorio


def main() -> None:
    p = argparse.ArgumentParser(description="Relatório de um dia ou de um período de contagem")
    p.add_argument("camera", nargs="?", default=None, help="Id da câmera em config/cameras.yaml")
    p.add_argument("--todas", action="store_true", help="Todas as câmeras juntas")
    p.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: hoje)")
    p.add_argument("--periodo", default=None, metavar="NOME",
                   help="Relatório de um período de teste (scripts/periodo.py --listar)")
    p.add_argument("--saida", default=None, help="Caminho do .md (padrão: dados/saidas/)")
    args = p.parse_args()

    if not args.periodo and not args.camera and not args.todas:
        sys.exit("Passe a câmera (ex.: entrada_real), --todas, ou --periodo \"Nome\".")

    config.garantir_pastas()
    conn = repositorio.conectar()
    try:
        if args.periodo:
            periodo = repositorio.periodo_por_nome(conn, args.periodo)
            if periodo is None:
                sys.exit(f"Período '{args.periodo}' não existe. Veja scripts/periodo.py --listar.")
            texto = relatorio.gerar_periodo(conn, periodo)
            nome_arquivo = f"relatorio_{relatorio.slug(periodo.nome)}.md"
        else:
            dia = date.fromisoformat(args.data) if args.data else date.today()
            camera = None if args.todas else args.camera
            texto = relatorio.gerar(conn, dia, camera)
            nome_arquivo = f"relatorio_{dia.isoformat()}_{camera or 'todas'}.md"
    finally:
        conn.close()

    destino = Path(args.saida) if args.saida else config.CAMINHO_SAIDAS / nome_arquivo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")

    print(texto)
    print(f"---\nGravado em {destino}")


if __name__ == "__main__":
    main()
