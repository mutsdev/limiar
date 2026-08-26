"""Desenha a linha de contagem clicando no primeiro quadro do vídeo.

    python scripts/calibrar_linha.py --camera entrada_a --fonte dados/videos/porta.mp4

Clique dois pontos. Depois clique um terceiro, do lado DE DENTRO do prédio, e
o script deduz o sinal. Tecla `r` recomeça, `Enter` grava, `Esc` cancela.

Isto é um passo próprio, e não um número editado à mão no código, porque sem
ferramenta ninguém recalibra — e recalibrar é a primeira coisa a fazer quando
a contagem erra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2

from fluxo import config
from fluxo.contagem import geometria

JANELA = "Calibrar linha  |  2 cliques = linha, 3o clique = lado DE DENTRO"


def main() -> None:
    p = argparse.ArgumentParser(description="Calibração da linha de contagem")
    p.add_argument("--camera", required=True)
    p.add_argument("--fonte", default=None, help="Sobrescreve a fonte do YAML")
    p.add_argument("--quadro", type=int, default=0, help="Qual quadro usar de base")
    args = p.parse_args()

    cameras = config.carregar_cameras()
    if args.camera not in cameras:
        sys.exit(f"Câmera '{args.camera}' não existe em {config.ARQUIVO_CAMERAS}")

    fonte = args.fonte or cameras[args.camera].get("fonte")
    if not fonte:
        sys.exit(f"Câmera '{args.camera}' não tem fonte. Passe --fonte.")

    cap = cv2.VideoCapture(str(fonte))
    if not cap.isOpened():
        sys.exit(f"Não consegui abrir: {fonte}")
    if args.quadro:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.quadro)
    ok, base = cap.read()
    cap.release()
    if not ok:
        sys.exit("Não consegui ler o quadro.")

    cliques: list[tuple[int, int]] = []

    def ao_clicar(evento, x, y, _flags, _param):
        if evento == cv2.EVENT_LBUTTONDOWN and len(cliques) < 3:
            cliques.append((x, y))

    cv2.namedWindow(JANELA, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(JANELA, ao_clicar)

    while True:
        tela = base.copy()
        for i, c in enumerate(cliques):
            cor = (59, 169, 242) if i < 2 else (180, 195, 67)
            cv2.circle(tela, c, 6, cor, -1)
        if len(cliques) >= 2:
            cv2.line(tela, cliques[0], cliques[1], (59, 169, 242), 2)
        if len(cliques) == 3:
            cv2.putText(
                tela, "DENTRO", (cliques[2][0] + 10, cliques[2][1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 195, 67), 2,
            )

        dica = {0: "Clique o inicio da linha", 1: "Clique o fim da linha",
                2: "Clique um ponto DE DENTRO do predio"}.get(
            len(cliques), "Enter grava  |  r recomeca  |  Esc cancela")
        cv2.putText(tela, dica, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (245, 245, 245), 2, cv2.LINE_AA)

        cv2.imshow(JANELA, tela)
        tecla = cv2.waitKey(20) & 0xFF
        if tecla == 27:
            cv2.destroyAllWindows()
            sys.exit("Cancelado.")
        if tecla in (ord("r"), ord("R")):
            cliques.clear()
        if tecla in (13, 10) and len(cliques) == 3:
            break

    cv2.destroyAllWindows()

    (x1, y1), (x2, y2), dentro = cliques
    lado_dentro = geometria.lado((x1, y1), (x2, y2), dentro)
    if lado_dentro == 0:
        sys.exit("O ponto 'dentro' caiu sobre a própria linha. Rode de novo.")

    cameras[args.camera]["linha"] = [int(x1), int(y1), int(x2), int(y2)]
    cameras[args.camera]["lado_dentro"] = int(lado_dentro)
    if args.fonte:
        cameras[args.camera]["fonte"] = str(args.fonte)
    config.salvar_cameras(cameras)

    print(f"Gravado em {config.ARQUIVO_CAMERAS}")
    print(f"  {args.camera}: linha=[{x1}, {y1}, {x2}, {y2}] lado_dentro={lado_dentro}")


if __name__ == "__main__":
    main()
