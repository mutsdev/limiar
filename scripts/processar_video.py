"""Roda o pipeline de contagem sobre um vídeo (ou câmera ao vivo).

    # só contar e gravar o vídeo anotado, sem tocar no banco
    python scripts/processar_video.py --camera entrada_a --sem-envio --anotar

    # contar e entregar ao serviço central
    python scripts/processar_video.py --camera entrada_a
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.agente import processador
from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.remetente import Remetente
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.visao.anotador import GravadorDeVideo
from fluxo.visao.fonte import FonteDeVideo
from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas


def main() -> None:
    p = argparse.ArgumentParser(description="Contagem de fluxo a partir de vídeo")
    p.add_argument("--camera", required=True)
    p.add_argument("--fonte", default=None, help="Sobrescreve a fonte do YAML")
    p.add_argument("--anotar", nargs="?", const="auto", default=None,
                   help="Grava o vídeo anotado (caminho, ou vazio para automático)")
    p.add_argument("--limite", type=int, default=None, help="Máximo de quadros")
    p.add_argument("--sem-envio", action="store_true", help="Não entrega ao serviço")
    p.add_argument("--modelo", default=None, help="Sobrescreve o modelo do YAML")
    p.add_argument("--inicio", default=None,
                   help="Instante do 1o quadro (ISO). Padrão: mtime do arquivo.")
    p.add_argument("--tempo-real", action="store_true",
                   help="Respeita o relógio, simulando câmera ao vivo")
    p.add_argument("--velocidade", type=float, default=1.0)
    args = p.parse_args()

    config.garantir_pastas()
    cameras = config.carregar_cameras()
    pipeline = config.carregar_pipeline()

    if args.camera not in cameras:
        sys.exit(f"Câmera '{args.camera}' não existe em {config.ARQUIVO_CAMERAS}")
    camera = cameras[args.camera]

    fonte_str = args.fonte or camera.get("fonte")
    if not fonte_str:
        sys.exit(f"Câmera '{args.camera}' não tem fonte. Passe --fonte.")

    linha = LinhaDeContagem.de_config(args.camera, camera, pipeline)

    cfg_visao = ConfigVisao.de_pipeline(pipeline)
    if args.modelo:
        cfg_visao.modelo = args.modelo

    inicio = datetime.fromisoformat(args.inicio).replace(tzinfo=FUSO_LOCAL) if args.inicio else None
    inicio = processador.instante_inicial_de(fonte_str, inicio)

    fonte = FonteDeVideo(
        fonte_str,
        instante_inicial=inicio,
        tempo_real=args.tempo_real,
        velocidade=args.velocidade,
        pular_quadros=int(pipeline.get("deteccao", {}).get("pular_quadros", 0)),
    )
    rastreador = RastreadorPessoas(cfg_visao)

    remetente = None
    if not args.sem_envio:
        fila = FilaLocal(config.CAMINHO_DADOS / "fila" / f"{args.camera}.jsonl")
        remetente = Remetente(config.URL_SERVICO, fila)
        if not remetente.servico_no_ar():
            print(f"AVISO: serviço fora do ar em {config.URL_SERVICO}. "
                  f"Os eventos vão para a fila local e serão reenviados depois.")

    gravador = None
    if args.anotar:
        destino = (
            config.CAMINHO_SAIDAS / f"{args.camera}_{Path(str(fonte_str)).stem}_anotado.mp4"
            if args.anotar == "auto"
            else Path(args.anotar)
        )
        gravador = GravadorDeVideo(destino, fonte.largura, fonte.altura, fonte.fps)

    print(f"Fonte    : {fonte}")
    print(f"Modelo   : {cfg_visao.modelo} em {rastreador.dispositivo}")
    print(f"Linha    : {linha.a} -> {linha.b}  (dentro = {linha.lado_dentro})")
    print(f"Início   : {inicio:%d/%m/%Y %H:%M:%S}")
    print()

    execucao_id = None
    if remetente is not None:
        execucao_id = remetente.abrir_execucao(
            args.camera, str(fonte_str), cfg_visao.modelo,
            cfg_visao.tracker, cfg_visao.confianca_minima,
            processador.versao_do_codigo(),
        )

    try:
        resultado = processador.processar(
            fonte, rastreador, linha, remetente, gravador, args.limite
        )
    finally:
        fonte.fechar()
        if gravador is not None:
            gravador.fechar()

    if remetente is not None and execucao_id is not None:
        remetente.fechar_execucao(
            execucao_id, resultado.quadros, len(resultado.eventos)
        )

    print()
    print(f"Quadros  : {resultado.quadros}  ({resultado.fps:.1f} q/s)")
    print(f"ENTRADAS : {resultado.entradas}")
    print(f"SAIDAS   : {resultado.saidas}")
    print(f"Saldo    : {resultado.entradas - resultado.saidas}")
    if remetente is not None:
        print(f"Enviados : {remetente.enviados}  | em fila: {remetente.fila.tamanho}")
    if gravador is not None:
        print(f"Vídeo    : {gravador.caminho}")


if __name__ == "__main__":
    main()
