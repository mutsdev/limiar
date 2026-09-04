"""Procura a câmera na rede local e, se você quiser, já grava o endereço.

    python scripts/achar_camera.py
    python scripts/achar_camera.py --atualizar entrada_real
    python scripts/achar_camera.py --rede 10.254.161.0/24

Serve para quando o IP muda — o que acontece a cada reinício da placa, e
portanto toda vez que ela sai do USB e vai para a tomada.

A câmera precisa estar **na mesma rede** que este computador. O SSID e a senha
ficam gravados dentro do firmware: numa rede diferente daquela em que a placa
foi programada, ela não aparece aqui, e nenhuma varredura vai achá-la.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import garantir_venv

garantir_venv(exigir_visao=False)

from fluxo import config
from fluxo.operacao import descoberta


def main() -> None:
    p = argparse.ArgumentParser(description="Acha a câmera MJPEG na rede local")
    p.add_argument("--rede", default=None,
                   help="Faixa a varrer (ex.: 10.1.0.0/24). Padrão: as desta máquina.")
    p.add_argument("--porta", type=int, default=descoberta.PORTA_STREAM)
    p.add_argument("--atualizar", default=None, metavar="CAMERA",
                   help="Grava a URL encontrada nesta câmera do cameras.yaml")
    args = p.parse_args()

    if args.rede:
        redes = [args.rede]
    else:
        locais = descoberta.ips_locais()
        if not locais:
            sys.exit("Não achei nenhum endereço IPv4 nesta máquina. Você está em rede?")
        print(f"Endereços desta máquina: {', '.join(locais)}")
        redes = descoberta.redes_para_varrer(locais)

    candidatos: list[str] = []
    for rede in redes:
        print(f"Varrendo {rede} na porta {args.porta}...", flush=True)
        candidatos += [ip for ip in descoberta.varrer(rede, args.porta)
                       if ip not in candidatos]

    if not candidatos:
        sys.exit(
            "\nNenhum dispositivo com a porta aberta.\n"
            "  - A placa está ligada e o LED aceso?\n"
            "  - Ela foi gravada com o SSID e a senha DESTA rede?\n"
            "  - Este computador está no mesmo wifi (não no cabo de outra rede)?"
        )

    print(f"Porta {args.porta} aberta em: {', '.join(candidatos)}")
    print("Confirmando qual serve MJPEG (um por vez — a placa só atende um cliente)...")
    cameras = descoberta.confirmar(candidatos, args.porta)

    if not cameras:
        sys.exit(
            "\nA porta abre, mas ninguém respondeu MJPEG.\n"
            "Se a câmera está nessa lista, provavelmente há OUTRO cliente "
            "conectado nela — feche a aba do navegador e tente de novo."
        )

    print()
    for ip in cameras:
        print(f"  CÂMERA: {descoberta.url_do_stream(ip, args.porta)}")

    if not args.atualizar:
        print("\nPara gravar no cameras.yaml:")
        print("  python scripts/achar_camera.py --atualizar entrada_real")
        return

    if len(cameras) > 1:
        sys.exit(f"\nAchei {len(cameras)} câmeras; passe --rede para desempatar.")

    cameras_yaml = config.carregar_cameras()
    if args.atualizar not in cameras_yaml:
        sys.exit(f"\nCâmera '{args.atualizar}' não existe em {config.ARQUIVO_CAMERAS}.")

    url = descoberta.url_do_stream(cameras[0], args.porta)
    anterior = cameras_yaml[args.atualizar].get("fonte")
    if anterior == url:
        print(f"\n'{args.atualizar}' já aponta para {url} — nada a mudar.")
        return

    cameras_yaml[args.atualizar]["fonte"] = url
    config.salvar_cameras(cameras_yaml)
    print(f"\n{args.atualizar}: {anterior}")
    print(f"        -> {url}")
    print("\nA LINHA de contagem continua a mesma. Ela vale em pixels do quadro, "
          "então só precisa ser recalibrada se a câmera mudou de lugar ou de resolução.")


if __name__ == "__main__":
    main()
