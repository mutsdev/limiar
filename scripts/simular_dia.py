"""Popula o banco com dias sintéticos.

Serve para construir e demonstrar painel e consultas antes de a visão
computacional existir.

    python scripts/simular_dia.py --dias 14
    python scripts/simular_dia.py --dias 14 --direto   # sem passar pela API
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from fluxo import config
from fluxo.persistencia import repositorio
from fluxo.simulacao import gerador


def main() -> None:
    p = argparse.ArgumentParser(description="Gerador de eventos sintéticos")
    p.add_argument("--dias", type=int, default=14)
    p.add_argument("--fim", default=None, help="Último dia (AAAA-MM-DD). Padrão: ontem.")
    p.add_argument("--pessoas", type=int, default=900, help="Pessoas por dia útil")
    p.add_argument("--semente", type=int, default=42)
    p.add_argument("--url", default=config.URL_SERVICO)
    p.add_argument(
        "--direto",
        action="store_true",
        help="Grava direto no banco em vez de enviar pela API.",
    )
    args = p.parse_args()

    fim = date.fromisoformat(args.fim) if args.fim else date.today() - timedelta(days=1)
    inicio = fim - timedelta(days=args.dias - 1)

    eventos = gerador.gerar_periodo(inicio, args.dias, args.pessoas, args.semente)
    print(f"Gerados {len(eventos)} eventos de {inicio} a {fim}.")

    if args.direto:
        config.garantir_pastas()
        conn = repositorio.conectar()
        try:
            repositorio.criar_banco(conn)
            for id_, nome, local, ativa in repositorio.cameras_do_yaml():
                repositorio.inserir_camera(conn, id_, nome, local, ativa)
            registrados, duplicados = repositorio.inserir_eventos(conn, eventos)
        finally:
            conn.close()
        print(f"Gravados: {registrados} | duplicados: {duplicados}")
        print(f"Banco: {config.CAMINHO_BANCO}")
        return

    # Envia em lotes: um POST por evento seria lento e sem necessidade.
    tamanho = 500
    registrados = duplicados = 0
    with httpx.Client(base_url=args.url, timeout=60.0) as cliente:
        cliente.get("/saude").raise_for_status()
        for i in range(0, len(eventos), tamanho):
            fatia = eventos[i : i + tamanho]
            corpo = [e.model_dump(mode="json") for e in fatia]
            r = cliente.post("/eventos/lote", json=corpo)
            r.raise_for_status()
            dados = r.json()
            registrados += dados["registrados"]
            duplicados += dados["duplicados"]
            print(f"  lote {i // tamanho + 1}: {dados['registrados']} gravados")

    print(f"Total gravado: {registrados} | duplicados: {duplicados}")


if __name__ == "__main__":
    main()
