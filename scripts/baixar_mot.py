"""Baixa sequências anotadas do MOT17 para a avaliação.

    python scripts/baixar_mot.py                 # as três de câmera estática
    python scripts/baixar_mot.py --sequencias MOT17-09

O site oficial (motchallenge.net) está inacessível desta rede, então as
sequências vêm de um espelho no HuggingFace. O conteúdo é o mesmo: `gt/gt.txt`
no formato MOTChallenge e `img1/` com os quadros.

**Só sequências de câmera estática.** MOT17-05, -10, -11 e -13 têm câmera em
movimento, e uma linha virtual fixa não tem significado quando o quadro se
desloca — o número que sairia dali não mediria nada.

Licença: MOT17 é distribuído sob CC BY-NC-SA 3.0 (uso não comercial, com
atribuição). Uso acadêmico está coberto; registre a atribuição no relatório.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config

ESPELHO = "Morrison1025/MOT17"

# nome -> (quadros, por que serve)
ESTATICAS = {
    "MOT17-09": (525, "calçada movimentada, câmera baixa e fixa"),
    "MOT17-02": (600, "praça, câmera fixa, fluxo cruzado"),
    "MOT17-04": (1050, "câmera alta e fixa, multidão densa"),
}

EM_MOVIMENTO = ("MOT17-05", "MOT17-10", "MOT17-11", "MOT17-13")


def baixar(nome: str, destino: Path) -> Path:
    from huggingface_hub import snapshot_download

    pasta_final = destino / nome
    if (pasta_final / "gt" / "gt.txt").exists():
        print(f"  {nome}: já baixada em {pasta_final}")
        return pasta_final

    # O espelho usa o sufixo -FRCNN; o conteúdo de imagem e anotação é o mesmo
    # nas três variantes (DPM/FRCNN/SDP), que só diferem no detector fornecido.
    origem = f"train/{nome}-FRCNN"
    print(f"  {nome}: baixando {origem} ...")
    caminho = snapshot_download(
        repo_id=ESPELHO,
        repo_type="dataset",
        allow_patterns=[f"{origem}/gt/*", f"{origem}/img1/*", f"{origem}/seqinfo.ini"],
        max_workers=8,
    )

    baixado = Path(caminho) / origem
    pasta_final.mkdir(parents=True, exist_ok=True)
    for sub in ("gt", "img1"):
        alvo = pasta_final / sub
        if alvo.exists():
            shutil.rmtree(alvo)
        shutil.copytree(baixado / sub, alvo)
    if (baixado / "seqinfo.ini").exists():
        shutil.copy2(baixado / "seqinfo.ini", pasta_final / "seqinfo.ini")

    return pasta_final


def main() -> None:
    p = argparse.ArgumentParser(description="Sequências anotadas do MOT17")
    p.add_argument("--sequencias", nargs="*", default=list(ESTATICAS),
                   help=f"Padrão: {' '.join(ESTATICAS)}")
    p.add_argument("--destino", default=None)
    args = p.parse_args()

    config.garantir_pastas()
    destino = Path(args.destino) if args.destino else config.CAMINHO_VIDEOS
    destino.mkdir(parents=True, exist_ok=True)

    for nome in args.sequencias:
        if nome in EM_MOVIMENTO:
            sys.exit(
                f"{nome} tem câmera em movimento. Uma linha virtual fixa não "
                f"tem significado quando o quadro se desloca — use "
                f"{', '.join(ESTATICAS)}."
            )
        if nome not in ESTATICAS:
            sys.exit(f"Não conheço '{nome}'. Disponíveis: {', '.join(ESTATICAS)}")

    print(f"Destino: {destino}\n")
    for nome in args.sequencias:
        quadros, motivo = ESTATICAS[nome]
        print(f"{nome} — {quadros} quadros, {motivo}")
        pasta = baixar(nome, destino)
        imagens = len(list((pasta / "img1").glob("*.jpg")))
        print(f"  pronto: {imagens} quadros em {pasta}\n")

    print("Próximo passo — descobrir onde pôr a linha:")
    for nome in args.sequencias:
        print(f"  python scripts/avaliar.py --mot {destino / nome} --sugerir-linha")


if __name__ == "__main__":
    main()
