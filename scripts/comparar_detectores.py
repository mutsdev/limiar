"""Roda YOLO e a linha de base MOG2 sobre o mesmo vídeo, com a mesma linha.

    python scripts/comparar_detectores.py --camera entrada_a

O único componente trocado é o detector. Linha, histerese, cooldown e direção
são os mesmos nos dois — sem isso a diferença não teria explicação única.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.avaliacao.baseline_mog2 import ConfigFundo, DetectorFundo
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.visao.fonte import FonteDeVideo
from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas


def rodar(nome, detector, camera_id, camera, pipeline, fonte_str, limite):
    fonte = FonteDeVideo(fonte_str)
    linha = LinhaDeContagem.de_config(camera_id, camera, pipeline)
    inicio = time.monotonic()
    quadros = 0
    try:
        for quadro in fonte:
            if limite is not None and quadros >= limite:
                break
            linha.processar(quadro.indice, quadro.instante, detector.atualizar(quadro.imagem))
            quadros += 1
    finally:
        fonte.fechar()
    segundos = time.monotonic() - inicio
    return {
        "nome": nome,
        "entradas": linha.entradas,
        "saidas": linha.saidas,
        "quadros": quadros,
        "qps": quadros / segundos if segundos else 0.0,
        "dispositivo": detector.dispositivo,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="YOLO x subtração de fundo")
    p.add_argument("--camera", required=True)
    p.add_argument("--fonte", default=None)
    p.add_argument("--limite", type=int, default=None)
    args = p.parse_args()

    cameras = config.carregar_cameras()
    pipeline = config.carregar_pipeline()
    if args.camera not in cameras:
        sys.exit(f"Câmera '{args.camera}' não existe.")
    camera = cameras[args.camera]
    fonte_str = args.fonte or camera.get("fonte")

    resultados = [
        rodar("YOLO11 + ByteTrack",
              RastreadorPessoas(ConfigVisao.de_pipeline(pipeline)),
              args.camera, camera, pipeline, fonte_str, args.limite),
        rodar("MOG2 + vizinho proximo",
              DetectorFundo(ConfigFundo()),
              args.camera, camera, pipeline, fonte_str, args.limite),
    ]

    print()
    print(f"{'metodo':<24} {'disp':>5} {'entradas':>9} {'saidas':>7} {'total':>6} {'q/s':>7}")
    print("-" * 64)
    for r in resultados:
        total = r["entradas"] + r["saidas"]
        print(f"{r['nome']:<24} {r['dispositivo']:>5} {r['entradas']:>9} "
              f"{r['saidas']:>7} {total:>6} {r['qps']:>7.1f}")
    print()

    yolo, base = resultados
    t_yolo = yolo["entradas"] + yolo["saidas"]
    t_base = base["entradas"] + base["saidas"]
    print(f"Divergencia entre os metodos: {abs(t_yolo - t_base)} passagens "
          f"({t_base} contra {t_yolo}).")
    print("Qual esta certo depende da contagem manual de referencia — ver")
    print("docs/avaliacao.md, secao 'Contagem manual'.")


if __name__ == "__main__":
    main()
