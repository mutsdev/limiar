"""Baixa o cloudflared para a pasta de ferramentas do projeto, sem admin.

    python scripts/instalar_tunel.py
    python scripts/instalar_tunel.py --forcar    # baixa de novo por cima

Se já houver um `cloudflared` no PATH (ou em CLOUDFLARED no .env), não faz
nada. O binário fica em ~/Documents/dados-fluxo/ferramentas/ — fora do
repositório e do OneDrive. O supervisor o encontra sozinho
(fluxo.operacao.tunel.localizar_cloudflared).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.operacao import tunel


def baixar(destino: Path) -> None:
    import httpx

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".baixando")
    print(f"Baixando {tunel.URL_DOWNLOAD}")
    with httpx.stream("GET", tunel.URL_DOWNLOAD, follow_redirects=True, timeout=60.0) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        lidos = 0
        with temporario.open("wb") as f:
            for pedaco in r.iter_bytes(1024 * 256):
                f.write(pedaco)
                lidos += len(pedaco)
                if total:
                    print(f"\r  {lidos / 1e6:.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    temporario.replace(destino)


def main() -> None:
    p = argparse.ArgumentParser(description="Instala o cloudflared para o túnel do painel")
    p.add_argument("--forcar", action="store_true", help="Baixa mesmo que já exista")
    args = p.parse_args()

    config.garantir_pastas()
    existente = None if args.forcar else tunel.localizar_cloudflared()
    if existente is not None:
        print(f"cloudflared já está em {existente}. Nada a fazer.")
        return

    destino = config.CAMINHO_FERRAMENTAS / tunel.NOME_EXE
    baixar(destino)
    print(f"Pronto: {destino}\nAgora: python scripts/rodar_tudo.py entrada_real --tunel")


if __name__ == "__main__":
    main()
