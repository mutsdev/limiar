"""Reconta uma trilha já gravada, sem GPU e sem abrir o vídeo.

A visão roda uma vez e deixa a trilha; a contagem roda quantas vezes for
preciso. É o que torna a calibração uma medição em vez de um palpite.

    # grava uma vez (precisa de GPU e do vídeo)
    python scripts/processar_video.py elevada --sem-envio --gravar-trilhas

    # reconta quantas vezes quiser (não precisa de nenhum dos dois)
    python scripts/reprocessar.py elevada
    python scripts/reprocessar.py elevada --costura 0        # o antes
    python scripts/reprocessar.py elevada --varredura

    # com referência anotada, sai o erro por direção
    python scripts/reprocessar.py mot17_09 --mot dados/videos/MOT17-09 --varredura
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.avaliacao import metricas, trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import Direcao

# A grade da varredura. Pequena de propósito: uma grade grande sobre uma
# sequência só não mede robustez, mede quantas combinações existem.
GRADE = {
    "costura_quadros": [0, 5, 15, 30],
    "costura_raio_px": [40.0, 80.0, 160.0],
}


def montar_linha(camera_id: str, **override) -> LinhaDeContagem:
    cameras = config.carregar_cameras()
    if camera_id not in cameras:
        sys.exit(f"Câmera '{camera_id}' não existe em {config.ARQUIVO_CAMERAS}")
    linha = LinhaDeContagem.de_config(
        camera_id, cameras[camera_id], config.carregar_pipeline()
    )
    for chave, valor in override.items():
        if valor is not None:
            setattr(linha, chave, valor)
    return linha


def referencia_mot(caminho: Path, camera_id: str, **override) -> tuple[int, int]:
    """Quantas travessias existiriam com rastreio perfeito, sob os MESMOS limiares.

    Os parâmetros variados na varredura entram aqui também. Se a referência
    ficasse presa nos valores do YAML enquanto a medição muda, a comparação
    deixaria de isolar a qualidade da visão — que é a única coisa que ela
    deveria estar medindo.
    """
    from datetime import datetime

    from fluxo.avaliacao import ground_truth as gt
    from fluxo.dominio.evento import FUSO_LOCAL

    sequencia = gt.carregar_mot(caminho)
    eventos = gt.contar_no_ground_truth(
        sequencia,
        montar_linha(camera_id, **override),
        datetime(2026, 1, 1, 8, 0, 0, tzinfo=FUSO_LOCAL),
    )
    return (
        sum(1 for e in eventos if e.direcao is Direcao.ENTRADA),
        sum(1 for e in eventos if e.direcao is Direcao.SAIDA),
    )


def uma_execucao(trilha: trilhas.Trilha, camera_id: str, **override):
    linha = montar_linha(camera_id, **override)
    eventos = trilhas.contar(trilha, linha)
    return linha, eventos


def relatar(trilha, camera_id, mot, **override) -> None:
    linha, eventos = uma_execucao(trilha, camera_id, **override)

    print(f"Trilha    : {trilha}")
    print(f"Linha     : {linha.a} -> {linha.b}  (dentro = {linha.lado_dentro})")
    print(f"Costura   : {linha.costura_quadros} quadros, raio "
          f"{linha.costura_raio_px:.0f} px  ->  {linha.costuras} rastros costurados")
    print()
    print(f"ENTRADAS  : {linha.entradas}")
    print(f"SAIDAS    : {linha.saidas}")
    print(f"Saldo     : {linha.entradas - linha.saidas}")

    # Sem referência anotada, este é o número que ainda diz alguma coisa:
    # acima de 1,00 é a mesma pessoa sendo contada mais de uma vez.
    cpp = trilhas.cruzamentos_por_pessoa(eventos)
    print(f"Cruzamentos por pessoa: {cpp:.2f}   (1,00 e o ideal)")

    if mot:
        entradas_gt, saidas_gt = referencia_mot(Path(mot), camera_id, **override)
        print()
        print("REFERENCIA: anotacao humana pela mesma linha e mesmos limiares")
        print(metricas.avaliar(
            linha.entradas, linha.saidas, entradas_gt, saidas_gt
        ).relatorio())


def varrer(trilha, camera_id, mot) -> None:
    print(f"Trilha    : {trilha}")
    print(f"Varredura : {len(GRADE['costura_quadros'])} x "
          f"{len(GRADE['costura_raio_px'])} combinacoes")
    print()
    cabecalho = (f"{'costura':>8} {'raio':>6} {'costuras':>9} "
                 f"{'entr':>6} {'said':>6} {'cruz/pes':>9}")
    if mot:
        cabecalho += f" {'ref e':>6} {'ref s':>6} {'erro e':>8} {'erro s':>8}"
    print(cabecalho)
    print("-" * len(cabecalho))

    for quadros in GRADE["costura_quadros"]:
        for raio in GRADE["costura_raio_px"]:
            override = {"costura_quadros": quadros, "costura_raio_px": raio}
            linha, eventos = uma_execucao(trilha, camera_id, **override)
            cpp = trilhas.cruzamentos_por_pessoa(eventos)
            texto = (f"{quadros:>8} {raio:>6.0f} {linha.costuras:>9} "
                     f"{linha.entradas:>6} {linha.saidas:>6} {cpp:>9.2f}")
            if mot:
                ent_gt, sai_gt = referencia_mot(Path(mot), camera_id, **override)
                aval = metricas.avaliar(linha.entradas, linha.saidas, ent_gt, sai_gt)
                texto += (f" {ent_gt:>6} {sai_gt:>6} "
                          f"{aval.entrada.erro_percentual:>7.1f}% "
                          f"{aval.saida.erro_percentual:>7.1f}%")
            print(texto)
            # A costura sem lacuna nenhuma é sempre a mesma execução: com
            # costura_quadros=0 o raio não muda nada, e repetir a linha daria
            # a impressão falsa de que foram testadas três configurações.
            if quadros == 0:
                break

    print()
    print("A combinacao escolhida vai declarada em config/pipeline.yaml e em")
    print("docs/resultados.md, com esta tabela ao lado. Escolher o melhor numero")
    print("de uma sequencia so e chamar isso de acuracia seria ajuste ao teste.")


def main() -> None:
    p = argparse.ArgumentParser(description="Reconta uma trilha gravada")
    p.add_argument("camera", help="Id da câmera (a trilha é dados/trilhas/<id>.jsonl)")
    p.add_argument("--trilha", default=None, help="Caminho explícito da trilha")
    p.add_argument("--mot", default=None,
                   help="Pasta da sequência MOTChallenge, para sair o erro medido")
    p.add_argument("--varredura", action="store_true",
                   help="Roda a grade de parâmetros de costura e imprime a tabela")
    p.add_argument("--costura", type=int, default=None,
                   help="Sobrescreve costura_quadros (0 desliga)")
    p.add_argument("--raio", type=float, default=None,
                   help="Sobrescreve costura_raio_px")
    p.add_argument("--zona-morta", type=float, default=None)
    p.add_argument("--cooldown", type=float, default=None)
    args = p.parse_args()

    caminho = Path(args.trilha) if args.trilha else (
        config.CAMINHO_DADOS / "trilhas" / f"{args.camera}.jsonl"
    )
    trilha = trilhas.carregar(caminho)

    if args.varredura:
        varrer(trilha, args.camera, args.mot)
        return

    relatar(
        trilha, args.camera, args.mot,
        costura_quadros=args.costura,
        costura_raio_px=args.raio,
        zona_morta_px=args.zona_morta,
        cooldown_segundos=args.cooldown,
    )


if __name__ == "__main__":
    main()
