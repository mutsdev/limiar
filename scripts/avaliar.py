"""Mede o erro do contador contra uma referência.

Duas referências, duas perguntas:

    # "quanto o sistema erra naquela porta" — contagem manual de duas pessoas
    python scripts/avaliar.py --camera entrada_a --ground-truth dados/ground_truth/porta.csv

    # "quanto a detecção imperfeita custa" — anotação humana do MOTChallenge
    python scripts/avaliar.py --mot dados/videos/MOT17-09 --camera mot17_09

    # onde colocar a linha, a partir das trajetórias anotadas
    python scripts/avaliar.py --mot dados/videos/MOT17-09 --sugerir-linha
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.avaliacao import ground_truth as gt
from fluxo.avaliacao import metricas, trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao

INICIO_PADRAO = datetime(2026, 1, 1, 8, 0, 0, tzinfo=FUSO_LOCAL)


def _por_minuto(eventos, inicio, direcao) -> dict[int, int]:
    contagem: dict[int, int] = {}
    for e in eventos:
        if e.direcao is direcao:
            minuto = int((e.instante - inicio).total_seconds() // 60)
            contagem[minuto] = contagem.get(minuto, 0) + 1
    return contagem


def _linha_da_camera(camera_id: str):
    cameras = config.carregar_cameras()
    if camera_id not in cameras:
        sys.exit(f"Câmera '{camera_id}' não existe em {config.ARQUIVO_CAMERAS}")
    return LinhaDeContagem.de_config(camera_id, cameras[camera_id], config.carregar_pipeline())


# --------------------------------------------------------------------------
# Sugestão de linha a partir do ground truth
# --------------------------------------------------------------------------


def sugerir_linha(sequencia: gt.SequenciaMOT) -> None:
    """Propõe a vertical cruzada pelo maior número de pessoas anotadas.

    Serve para não repetir o erro do primeiro teste deste projeto, quando a
    linha caiu atrás de um pilar. Continua sendo uma sugestão: confira no
    quadro antes de aceitar, porque oclusor não aparece na trajetória.
    """
    faixas: dict[int, tuple[float, float]] = {}
    for rastros in sequencia.por_quadro.values():
        for r in rastros:
            x, _ = r.ponto_base
            menor, maior = faixas.get(r.id_local, (x, x))
            faixas[r.id_local] = (min(menor, x), max(maior, x))

    uteis = {i: f for i, f in faixas.items() if f[1] - f[0] > 30}
    if not uteis:
        sys.exit("Nenhuma pessoa anotada se desloca o bastante para cruzar uma linha.")

    largura = sequencia.largura or int(max(f[1] for f in uteis.values()) + 50)
    melhor_x, melhor_n = 0, 0
    for x in range(20, largura - 20, 5):
        n = sum(1 for menor, maior in uteis.values() if menor < x < maior)
        if n > melhor_n:
            melhor_x, melhor_n = x, n

    altura = sequencia.altura or 1080
    print(f"Sequência : {sequencia.nome}  ({sequencia.quadros} quadros, "
          f"{sequencia.fps:.0f} fps, {sequencia.pessoas} pessoas anotadas)")
    print(f"Trajetórias com deslocamento útil: {len(uteis)}")
    print()
    print(f"Melhor vertical: x = {melhor_x}, cruzada por {melhor_n} pessoas")
    print()
    print("Para usar, acrescente em config/cameras.yaml:")
    print(f"  linha: [{melhor_x}, 0, {melhor_x}, {altura}]")
    print("  lado_dentro: -1        # o lado direito do quadro")
    print()
    print("Confira no quadro antes de aceitar: oclusor (pilar, poste, muro) não")
    print("aparece na trajetória, e linha atrás de oclusor perde travessia.")


# --------------------------------------------------------------------------
# Avaliação contra o MOTChallenge
# --------------------------------------------------------------------------


def avaliar_mot(
    caminho: Path, camera_id: str, limite: int | None, sem_baseline: bool,
    visibilidade: float = 0.0, gravar_trilhas: bool = False,
) -> int:
    from fluxo.agente import processador
    from fluxo.visao.fonte import FonteDeVideo
    from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas

    sequencia = gt.carregar_mot(caminho, visibilidade_minima=visibilidade)
    pipeline = config.carregar_pipeline()

    # A referência: a anotação humana passando pela MESMA linha, com os mesmos
    # limiares. Só a qualidade da visão muda entre esta contagem e a medida.
    eventos_gt = gt.contar_no_ground_truth(sequencia, _linha_da_camera(camera_id), INICIO_PADRAO)

    fonte = FonteDeVideo(sequencia.padrao_imagens, instante_inicial=INICIO_PADRAO)
    fonte.fps = sequencia.fps
    rastreador = RastreadorPessoas(ConfigVisao.de_pipeline(pipeline))
    linha_medida = _linha_da_camera(camera_id)

    print(f"Sequência : {sequencia.nome}  ({sequencia.quadros} quadros, "
          f"{sequencia.pessoas} pessoas anotadas)")
    if visibilidade > 0:
        print(f"Referência: só pessoas com visibilidade >= {visibilidade:.0%}")
    print(f"Linha     : {linha_medida.a} -> {linha_medida.b} "
          f"(dentro = {linha_medida.lado_dentro})")
    print(f"Modelo    : {rastreador.config.modelo} em {rastreador.dispositivo}")
    print()

    trilha = None
    if gravar_trilhas:
        trilha = trilhas.Gravador(
            config.CAMINHO_DADOS / "trilhas" / f"{camera_id}.jsonl",
            camera=camera_id, fonte=sequencia.padrao_imagens, fps=sequencia.fps,
            largura=sequencia.largura, altura=sequencia.altura,
            modelo=rastreador.config.modelo, tracker=rastreador.config.tracker,
            confianca_minima=rastreador.config.confianca_minima,
        )

    resultado = processador.processar(
        fonte, rastreador, linha_medida, None, None, limite,
        mostrar_progresso=True, trilha=trilha,
    )
    fonte.fechar()
    if trilha is not None:
        trilha.fechar()
        print(f"Trilha    : {trilha.caminho}  ({trilha.quadros} quadros)")

    entradas_gt = sum(1 for e in eventos_gt if e.direcao is Direcao.ENTRADA)
    saidas_gt = sum(1 for e in eventos_gt if e.direcao is Direcao.SAIDA)

    mae = metricas.mae_por_janela(
        _por_minuto(resultado.eventos, INICIO_PADRAO, Direcao.ENTRADA),
        _por_minuto(eventos_gt, INICIO_PADRAO, Direcao.ENTRADA),
    )
    avaliacao = metricas.avaliar(
        resultado.entradas, resultado.saidas, entradas_gt, saidas_gt, mae_janela=mae
    )

    print()
    print("REFERENCIA: anotacao humana do MOTChallenge pela mesma linha")
    print(avaliacao.relatorio())
    print()
    print(f"Desempenho: {resultado.fps:.1f} quadros/s")

    if not sem_baseline:
        from fluxo.avaliacao.baseline_mog2 import DetectorFundo

        fonte_base = FonteDeVideo(sequencia.padrao_imagens, instante_inicial=INICIO_PADRAO)
        fonte_base.fps = sequencia.fps
        linha_base = _linha_da_camera(camera_id)
        base = processador.processar(
            fonte_base, DetectorFundo(), linha_base, None, None, limite,
            mostrar_progresso=True,
        )
        fonte_base.fechar()
        aval_base = metricas.avaliar(base.entradas, base.saidas, entradas_gt, saidas_gt)
        print()
        print("LINHA DE BASE: subtracao de fundo (MOG2), mesma linha e limiares")
        print(aval_base.relatorio())
        print()
        print(f"Desempenho: {base.fps:.1f} quadros/s")

    return 0 if avaliacao.aprovado else 1


# --------------------------------------------------------------------------
# Avaliação contra contagem manual
# --------------------------------------------------------------------------


def avaliar_manual(camera_id: str, caminho_csv: Path, limite: int | None) -> int:
    from fluxo.agente import processador
    from fluxo.visao.fonte import FonteDeVideo
    from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas

    referencia = gt.carregar_csv(caminho_csv)
    cameras = config.carregar_cameras()
    if camera_id not in cameras:
        sys.exit(f"Câmera '{camera_id}' não existe.")
    fonte_str = cameras[camera_id].get("fonte")
    if not fonte_str:
        sys.exit(f"Câmera '{camera_id}' não tem fonte configurada.")

    pipeline = config.carregar_pipeline()
    inicio = processador.instante_inicial_de(fonte_str, None)
    fonte = FonteDeVideo(fonte_str, instante_inicial=inicio)
    linha = _linha_da_camera(camera_id)

    print(f"Fonte      : {fonte}")
    print(f"Referência : {referencia.origem} "
          f"({len(referencia.por_minuto)} minutos contados à mão)")
    print()

    resultado = processador.processar(
        fonte, RastreadorPessoas(ConfigVisao.de_pipeline(pipeline)), linha,
        None, None, limite, mostrar_progresso=True,
    )
    fonte.fechar()

    mae = metricas.mae_por_janela(
        _por_minuto(resultado.eventos, inicio, Direcao.ENTRADA),
        referencia.entradas_por_minuto(),
    )
    avaliacao = metricas.avaliar(
        resultado.entradas, resultado.saidas,
        referencia.entradas, referencia.saidas, mae_janela=mae,
    )

    print()
    print("REFERENCIA: contagem manual")
    print(avaliacao.relatorio())
    return 0 if avaliacao.aprovado else 1


def main() -> None:
    p = argparse.ArgumentParser(description="Avaliação do contador")
    p.add_argument("--camera", default=None, help="Câmera de config/cameras.yaml")
    p.add_argument("--ground-truth", default=None, help="CSV da contagem manual")
    p.add_argument("--mot", default=None, help="Pasta de uma sequência do MOTChallenge")
    p.add_argument("--sugerir-linha", action="store_true",
                   help="Analisa as trajetórias anotadas e propõe onde pôr a linha")
    p.add_argument("--limite", type=int, default=None, help="Máximo de quadros")
    p.add_argument("--sem-baseline", action="store_true",
                   help="Pula a comparação com a subtração de fundo")
    p.add_argument("--gravar-trilhas", action="store_true",
                   help="Grava o que a visao enxergou, para reprocessar sem GPU")
    p.add_argument("--visibilidade", type=float, default=0.0,
                   help="Fração mínima de visibilidade para a pessoa entrar na "
                        "referência. O MOT17 anota gente quase toda ocluída, e "
                        "nenhum detector acha quem não está visível.")
    args = p.parse_args()

    if args.mot and args.sugerir_linha:
        sugerir_linha(gt.carregar_mot(Path(args.mot)))
        return

    if args.mot:
        if not args.camera:
            sys.exit("--mot precisa de --camera para saber onde está a linha calibrada.\n"
                     "Rode antes: --mot <pasta> --sugerir-linha")
        sys.exit(avaliar_mot(Path(args.mot), args.camera, args.limite,
                             args.sem_baseline, args.visibilidade,
                             args.gravar_trilhas))

    if args.ground_truth:
        if not args.camera:
            sys.exit("--ground-truth precisa de --camera.")
        sys.exit(avaliar_manual(args.camera, Path(args.ground_truth), args.limite))

    p.error("Escolha uma referência: --ground-truth <csv> ou --mot <pasta>")


if __name__ == "__main__":
    main()
