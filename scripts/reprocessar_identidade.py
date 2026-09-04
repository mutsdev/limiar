"""Reconta uma trilha/2 com a galeria de identidade — sem GPU, sem vídeo.

    # grava uma vez (precisa da câmera e da GPU)
    python scripts/identificar_pessoas.py entrada_real --sem-envio --gravar-trilhas

    # reconta quantas vezes quiser, mudando os limiares
    python scripts/reprocessar_identidade.py entrada_real
    python scripts/reprocessar_identidade.py entrada_real --limiar-saida 0.6 --janela 0
    python scripts/reprocessar_identidade.py entrada_real --varredura

    # com o gabarito preenchido, saem pureza e fragmentação por combinação
    python scripts/reprocessar_identidade.py entrada_real --varredura \\
        --gabarito dados/gabaritos/2026-09-04_entrada_real.csv

O irmão do reprocessar.py: aquele varre os parâmetros da contagem, este varre
os da identidade. A linha de contagem é a mesma do YAML nos dois.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.avaliacao import identidade as av
from fluxo.avaliacao import trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.reid import metricas
from fluxo.reid.galeria import Galeria


def montar_linha(camera_id: str) -> LinhaDeContagem:
    cameras = config.carregar_cameras()
    if camera_id not in cameras:
        sys.exit(f"Câmera '{camera_id}' não existe em {config.ARQUIVO_CAMERAS}")
    return LinhaDeContagem.de_config(camera_id, cameras[camera_id], config.carregar_pipeline())


def montar_galeria(**override) -> Galeria:
    galeria = Galeria.de_pipeline(config.carregar_pipeline())
    for chave, valor in override.items():
        if valor is not None:
            setattr(galeria, chave, valor)
    return galeria


def relatar(trilha: trilhas.Trilha, camera_id: str, gabarito: dict[str, str] | None,
            **override) -> None:
    galeria = montar_galeria(**override)
    linha = montar_linha(camera_id)
    eventos, decisoes = av.recontar(trilha, linha, galeria)
    registros = av.registros_de(decisoes)

    print(f"Trilha    : {trilha}")
    print(f"Re-ID     : {trilha.cabecalho.get('modelo_reid', '?')}  |  "
          f"{sum(len(v) for v in trilha.assinaturas.values())} assinaturas gravadas")
    print(f"Limiares  : saída {galeria.limiar_saida}  reentrada {galeria.limiar_reentrada}  "
          f"lote {galeria.janela_lote_s:.0f}s")
    print()
    print(f"ENTRADAS  : {linha.entradas}")
    print(f"SAIDAS    : {linha.saidas}")
    print(f"Pessoas   : {galeria.criadas} únicas  |  reentradas {galeria.reentradas}")
    saidas, sem_par, taxa = metricas.taxa_nao_atribuido(registros)
    print(f"Saídas    : atribuídas {galeria.atribuidas}  |  sem par {sem_par} "
          f"({taxa:.0%})  |  fantasmas {galeria.fantasmas}")
    sem_assinatura = len(eventos) - len(decisoes)
    if sem_assinatura:
        print(f"            {sem_assinatura} eventos sem assinatura na trilha (não decididos)")

    perms = metricas.permanencias(registros)
    if perms:
        media = sum(p.segundos for p in perms) / len(perms) / 60
        print(f"Permanência: {len(perms)} pares, média {media:.0f} min")

    print()
    print(f"{'P':<5} {'entra':>5} {'sai':>4}  {'primeira':<9} {'última':<9}")
    for p in sorted(galeria.pessoas.values(), key=lambda p: int(p.pseudonimo[1:])):
        print(f"{p.pseudonimo:<5} {p.entradas:>5} {p.saidas:>4}  "
              f"{p.primeiro_visto:%H:%M:%S}  {p.ultimo_visto:%H:%M:%S}")

    if gabarito:
        pu = metricas.pureza(registros, gabarito)
        fr = metricas.fragmentacao(registros, gabarito)
        print()
        print("GABARITO")
        print(f"  rotuladas   : {pu.total} travessias, {fr.pessoas} pessoas reais")
        print(f"  pureza      : {pu.taxa:.0%}  ({pu.confusoes} confusões)")
        print(f"  fragmentação: {fr.media:.2f} P por pessoa  ({fr.divididas} divididas)")
        for pseudonimo, (apelido, n, certos) in pu.por_pseudonimo.items():
            marca = "" if certos == n else f"   <- {n - certos} de outra pessoa"
            print(f"    {pseudonimo:<5} {apelido:<14} {certos}/{n}{marca}")


def varrer(trilha: trilhas.Trilha, camera_id: str, gabarito: dict[str, str] | None) -> None:
    base = montar_galeria()
    linhas = av.varrer(trilha, lambda: montar_linha(camera_id), base, gabarito)

    print(f"Trilha    : {trilha}")
    print(f"Varredura : {len(linhas)} combinações")
    print()
    cabecalho = (f"{'saída':>6} {'reentr':>6} {'lote':>5} {'pessoas':>7} "
                 f"{'reentr':>6} {'sem par':>8}")
    if gabarito:
        cabecalho += f" {'pureza':>7} {'frag':>5} {'confus':>6} {'divid':>5}"
    print(cabecalho)
    print("-" * len(cabecalho))
    for r in linhas:
        texto = (f"{r['limiar_saida']:>6.2f} {r['limiar_reentrada']:>6.2f} "
                 f"{r['janela_lote_s']:>5.0f} {r['pessoas']:>7} {r['reentradas']:>6} "
                 f"{r['sem_par']:>4} {r['taxa_sem_par']:>3.0%}")
        if gabarito:
            texto += (f" {r['pureza']:>7.0%} {r['fragmentacao']:>5.2f} "
                      f"{r['confusoes']:>6} {r['divididas']:>5}")
        print(texto)

    print()
    print("Escolha a combinação com pureza alta E fragmentação perto de 1 — as duas")
    print("puxam para lados opostos. A escolhida vai para config/pipeline.yaml e")
    print("docs/resultados.md, com esta tabela ao lado.")


def main() -> None:
    p = argparse.ArgumentParser(description="Reconta uma trilha/2 com a galeria de identidade")
    p.add_argument("camera", help="Id da câmera (a trilha é dados/trilhas/<id>.jsonl)")
    p.add_argument("--trilha", default=None, help="Caminho explícito da trilha")
    p.add_argument("--gabarito", default=None,
                   help="CSV preenchido por scripts/rotular_pessoas.py --gerar")
    p.add_argument("--varredura", action="store_true",
                   help="Roda a grade de limiares e imprime a tabela")
    p.add_argument("--limiar-saida", type=float, default=None)
    p.add_argument("--limiar-reentrada", type=float, default=None)
    p.add_argument("--janela", type=float, default=None, help="janela_lote_s (0 = imediato)")
    args = p.parse_args()

    caminho = Path(args.trilha) if args.trilha else config.CAMINHO_TRILHAS / f"{args.camera}.jsonl"
    trilha = trilhas.carregar(caminho)
    if not trilha.assinaturas:
        sys.exit(
            f"{caminho} não tem assinaturas. Grave com:\n"
            f"  python scripts/identificar_pessoas.py {args.camera} --sem-envio --gravar-trilhas"
        )
    gabarito = av.carregar_gabarito(args.gabarito) if args.gabarito else None

    if args.varredura:
        varrer(trilha, args.camera, gabarito)
        return
    relatar(
        trilha, args.camera, gabarito,
        limiar_saida=args.limiar_saida,
        limiar_reentrada=args.limiar_reentrada,
        janela_lote_s=args.janela,
    )


if __name__ == "__main__":
    main()
