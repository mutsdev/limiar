"""Roda o pipeline de contagem sobre um vídeo (ou câmera ao vivo).

    # ver a contagem acontecendo numa janela
    python scripts/processar_video.py porta --sem-envio --ao-vivo

    # ver e gravar ao mesmo tempo
    python scripts/processar_video.py porta --sem-envio --ao-vivo --anotar

    # contar e entregar ao serviço central
    python scripts/processar_video.py porta

Na janela: `q` sai, espaço pausa. `--escala 1.5` aumenta, `--velocidade 2`
acelera.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import garantir_venv, id_de_camera

# Reexecuta no ambiente do projeto se este `python` nao for o certo. Precisa
# vir antes de qualquer import que dependa das bibliotecas pesadas.
garantir_venv()

from fluxo import config
from fluxo.agente import processador
from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.remetente import Remetente
from fluxo.avaliacao import trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.visao.anotador import GravadorDeVideo, JanelaAoVivo
from fluxo.visao.fonte import FonteDeVideo
from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas


def main() -> None:
    p = argparse.ArgumentParser(description="Contagem de fluxo a partir de vídeo")
    p.add_argument("alvo", nargs="?", default=None,
                   help="Id da câmera calibrada, ou o caminho de um vídeo.")
    p.add_argument("--camera", default=None)
    p.add_argument("--fonte", default=None, help="Sobrescreve a fonte do YAML")
    p.add_argument("--anotar", nargs="?", const="auto", default=None,
                   help="Grava o vídeo anotado (caminho, ou vazio para automático)")
    p.add_argument("--limite", type=int, default=None, help="Máximo de quadros")
    p.add_argument("--sem-envio", action="store_true", help="Não entrega ao serviço")
    p.add_argument("--modelo", default=None, help="Sobrescreve o modelo do YAML")
    p.add_argument("--dispositivo", default=None,
                   help="'0' para GPU, 'cpu' para CPU. Duas GPUs concorrentes no "
                        "Windows serializam: rode a segunda camera em cpu.")
    p.add_argument("--inicio", default=None,
                   help="Instante do 1o quadro (ISO). Padrão: mtime do arquivo.")
    p.add_argument("--ao-vivo", action="store_true",
                   help="Abre uma janela e mostra a contagem acontecendo.")
    p.add_argument("--escala", type=float, default=1.0,
                   help="Aumenta ou reduz a janela (ex.: 1.5). Só afeta a exibição.")
    p.add_argument("--gravar-trilhas", action="store_true",
                   help="Grava o que a visão enxergou em dados/trilhas/<camera>.jsonl, "
                        "para reprocessar depois sem GPU (scripts/reprocessar.py).")
    p.add_argument("--tempo-real", action="store_true",
                   help="Respeita o relógio na LEITURA (para simular câmera ao vivo)")
    p.add_argument("--velocidade", type=float, default=1.0)
    args = p.parse_args()

    config.garantir_pastas()
    cameras = config.carregar_cameras()
    pipeline = config.carregar_pipeline()

    # O alvo pode ser um id ja calibrado ou um caminho de video.
    alvo = args.alvo or args.camera
    if not alvo:
        sys.exit("Passe a câmera ou o vídeo: python scripts/processar_video.py elevada")
    if alvo in cameras:
        args.camera = alvo
    elif Path(str(alvo)).exists():
        args.camera = id_de_camera(alvo)
        args.fonte = args.fonte or alvo
    else:
        args.camera = alvo

    if args.camera not in cameras:
        sys.exit(
            f"Câmera '{args.camera}' não existe em {config.ARQUIVO_CAMERAS}.\n"
            f"Calibre antes:\n"
            f'  python scripts/calibrar_linha.py "{alvo}"'
        )
    camera = cameras[args.camera]

    fonte_str = args.fonte or camera.get("fonte")
    if not fonte_str:
        sys.exit(f"Câmera '{args.camera}' não tem fonte. Passe --fonte.")

    linha = LinhaDeContagem.de_config(args.camera, camera, pipeline)

    cfg_visao = ConfigVisao.de_pipeline(pipeline)
    if args.modelo:
        cfg_visao.modelo = args.modelo
    if args.dispositivo:
        cfg_visao.dispositivo = args.dispositivo

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

    trilha = None
    if args.gravar_trilhas:
        trilha = trilhas.Gravador(
            config.CAMINHO_DADOS / "trilhas" / f"{args.camera}.jsonl",
            camera=args.camera,
            fonte=str(fonte_str),
            fps=fonte.fps,
            largura=fonte.largura,
            altura=fonte.altura,
            modelo=cfg_visao.modelo,
            tracker=cfg_visao.tracker,
            confianca_minima=cfg_visao.confianca_minima,
            versao=processador.versao_do_codigo(),
        )

    janela = None
    if args.ao_vivo:
        janela = JanelaAoVivo(
            f"Limiar - {args.camera}", fonte.fps, args.velocidade, args.escala
        )

    print(f"Fonte    : {fonte}")
    print(f"Modelo   : {cfg_visao.modelo} em {rastreador.dispositivo}")
    print(f"Linha    : {linha.a} -> {linha.b}  (dentro = {linha.lado_dentro})")
    print(f"Início   : {inicio:%d/%m/%Y %H:%M:%S}")
    if janela is not None:
        print("Janela   : ao vivo — q sai, espaço pausa")
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
            fonte, rastreador, linha, remetente, gravador, args.limite,
            janela=janela, trilha=trilha,
        )
    finally:
        fonte.fechar()
        if gravador is not None:
            gravador.fechar()
        if janela is not None:
            janela.fechar()
        if trilha is not None:
            trilha.fechar()

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
    if trilha is not None:
        print(f"Trilha   : {trilha.caminho}  ({trilha.quadros} quadros)")
        print(f"           reprocesse sem GPU: python scripts/reprocessar.py {args.camera}")


if __name__ == "__main__":
    main()
