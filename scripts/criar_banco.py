"""Cria o banco e cadastra as câmeras de config/cameras.yaml."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.persistencia import repositorio


def main() -> None:
    config.garantir_pastas()
    conn = repositorio.conectar()
    try:
        repositorio.criar_banco(conn)
        for id_, nome, local, ativa in repositorio.cameras_do_yaml():
            repositorio.inserir_camera(conn, id_, nome, local, ativa)
        cameras = repositorio.listar_cameras(conn)
    finally:
        conn.close()

    print(f"Banco: {config.CAMINHO_BANCO}")
    for c in cameras:
        estado = "ativa" if c["ativa"] else "inativa"
        print(f"  {c['id']:<12} {c['nome']} ({estado})")


if __name__ == "__main__":
    main()
