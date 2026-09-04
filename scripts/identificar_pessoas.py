"""Conta E identifica quem cruza a linha — a Etapa 2, num script próprio.

    # ver na tela, gravar trilha com assinaturas e miniaturas para rotular depois
    python scripts/identificar_pessoas.py entrada_real --sem-envio --gravar-trilhas \\
        --guardar-recortes

    # contar, identificar e entregar ao serviço
    python scripts/identificar_pessoas.py entrada_real

É o irmão do processar_video.py, que NÃO muda: aquele conta em produção; este
conta e diz que "P7 saiu". Mesma fonte, mesma linha, mesmo laço — com a camada
de identidade ligada. Na janela, a etiqueta da caixa é o pseudônimo do dia.

`--guardar-recortes` grava uma miniatura por travessia em dados/recortes/ —
imagem de pessoa real, fora do git. Só para o teste de validação com pessoas
conhecidas; em operação, nunca. Apague a pasta ao terminar.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import e_webcam, garantir_venv, id_de_camera, normalizar_fonte

# Reexecuta no ambiente do projeto se este `python` nao for o certo. Precisa
# vir antes de qualquer import que dependa das bibliotecas pesadas.
garantir_venv()

from fluxo import config
from fluxo.agente import processador
from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.identidade import Identidade
from fluxo.agente.remetente import Remetente
from fluxo.avaliacao import trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.reid.galeria import Galeria
from fluxo.visao.anotador import GravadorDeVideo, JanelaAoVivo
from fluxo.visao.aparencia import ConfigAparencia, Extrator
from fluxo.visao.fonte import FonteDeVideo
from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas


def main() -> None:
    p = argparse.ArgumentParser(description="Contagem com re-identificação anônima (Etapa 2)")
    p.add_argument("alvo", nargs="?", default=None,
                   help="Id da câmera calibrada, ou o caminho de um vídeo.")
    p.add_argument("--camera", default=None)
    p.add_argument("--fonte", default=None, help="Sobrescreve a fonte do YAML")
    p.add_argument("--anotar", nargs="?", const="auto", default=None,
                   help="Grava o vídeo anotado (caminho, ou vazio para automático)")
    p.add_argument("--limite", type=int, default=None, help="Máximo de quadros")
    p.add_argument("--sem-envio", action="store_true", help="Não entrega ao serviço")
    p.add_argument("--modelo", default=None, help="Sobrescreve o detector do YAML")
    p.add_argument("--modelo-reid", default=None,
                   help="Sobrescreve a rede de aparência do YAML (resnet18, resnet50)")
    p.add_argument("--dispositivo", default=None, help="'0' para GPU, 'cpu' para CPU.")
    p.add_argument("--inicio", default=None,
                   help="Instante do 1o quadro (ISO). Padrão: mtime do arquivo.")
    p.add_argument("--ao-vivo", action="store_true",
                   help="Abre uma janela e mostra a contagem acontecendo.")
    p.add_argument("--escala", type=float, default=1.0,
                   help="Aumenta ou reduz a janela (ex.: 1.5). Só afeta a exibição.")
    p.add_argument("--placar", type=float, default=None,
                   help="Tamanho do placar e das caixas. Por padrão compensa a --escala.")
    p.add_argument("--gravar-trilhas", action="store_true",
                   help="Grava trilha/2 (rastros + assinaturas) em dados/trilhas/<camera>.jsonl, "
                        "para varrer limiares depois sem GPU.")
    p.add_argument("--guardar-recortes", action="store_true",
                   help="Grava uma miniatura por travessia em dados/recortes/. SÓ para o "
                        "teste de validação. Apague ao terminar.")
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
        sys.exit("Passe a câmera ou o vídeo: python scripts/identificar_pessoas.py entrada_real")
    if alvo in cameras:
        args.camera = alvo
    elif e_webcam(alvo):
        args.camera = id_de_camera(alvo)
        args.fonte = args.fonte or alvo
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

    fonte_str = args.fonte if args.fonte is not None else camera.get("fonte")
    if fonte_str is None or fonte_str == "":
        sys.exit(f"Câmera '{args.camera}' não tem fonte. Passe --fonte.")
    fonte_str = normalizar_fonte(fonte_str)

    linha = LinhaDeContagem.de_config(args.camera, camera, pipeline)

    cfg_visao = ConfigVisao.de_pipeline(pipeline)
    if args.modelo:
        cfg_visao.modelo = args.modelo
    if args.dispositivo:
        cfg_visao.dispositivo = args.dispositivo

    cfg_reid = ConfigAparencia.de_pipeline(pipeline, pasta_modelos=config.CAMINHO_MODELOS)
    if args.modelo_reid:
        cfg_reid.modelo = args.modelo_reid
    if args.dispositivo:
        cfg_reid.dispositivo = args.dispositivo

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
    extrator = Extrator(cfg_reid)

    remetente = None
    if not args.sem_envio:
        fila = FilaLocal(config.CAMINHO_DADOS / "fila" / f"{args.camera}.jsonl")
        remetente = Remetente(config.URL_SERVICO, fila, chave=config.CHAVE_API)
        if not remetente.servico_no_ar():
            print(f"AVISO: serviço fora do ar em {config.URL_SERVICO}. "
                  f"Os eventos vão para a fila local e serão reenviados depois.")

    gravador = None
    if args.anotar:
        destino = (
            config.CAMINHO_SAIDAS / f"{args.camera}_{Path(str(fonte_str)).stem}_identidade.mp4"
            if args.anotar == "auto"
            else Path(args.anotar)
        )
        gravador = GravadorDeVideo(destino, fonte.largura, fonte.altura, fonte.fps)

    trilha = None
    if args.gravar_trilhas:
        trilha = trilhas.Gravador(
            config.CAMINHO_TRILHAS / f"{args.camera}.jsonl",
            camera=args.camera,
            fonte=str(fonte_str),
            fps=fonte.fps,
            largura=fonte.largura,
            altura=fonte.altura,
            modelo=cfg_visao.modelo,
            tracker=cfg_visao.tracker,
            confianca_minima=cfg_visao.confianca_minima,
            modelo_reid=cfg_reid.modelo,
            versao=processador.versao_do_codigo(),
        )

    pasta_recortes = config.CAMINHO_RECORTES if args.guardar_recortes else None
    identidade = Identidade(
        camera_id=args.camera,
        extrator=extrator,
        galeria=Galeria.de_pipeline(pipeline),
        recortes_por_track=cfg_reid.recortes_por_track,
        intervalo_recorte_quadros=cfg_reid.intervalo_recorte_quadros,
        esquecer_apos_quadros=linha.quadros_ate_esquecer,
        remetente=remetente if hasattr(remetente, "enviar_vinculos") else None,
        pasta_recortes=pasta_recortes,
        trilha=trilha,
    )

    # Câmera ao vivo não acaba. Sem janela e sem arquivo, o laço rodaria para
    # sempre sem nada na tela, e a única saída seria matar o processo.
    ao_vivo = args.ao_vivo
    if fonte.ao_vivo and not ao_vivo and not args.anotar:
        print("Fonte ao vivo: abrindo a janela (q encerra).")
        ao_vivo = True

    escala_placar = args.placar if args.placar else (
        1.0 / args.escala if ao_vivo and args.escala < 1.0 else 1.0
    )

    janela = None
    if ao_vivo:
        janela = JanelaAoVivo(
            f"Limiar - {args.camera} - identidade", fonte.fps, args.velocidade, args.escala
        )

    print(f"Fonte    : {fonte}")
    print(f"Detector : {cfg_visao.modelo} em {rastreador.dispositivo}")
    print(f"Re-ID    : {cfg_reid.modelo} em {extrator.dispositivo}  "
          f"(limiar saída {identidade.galeria.limiar_saida}, "
          f"reentrada {identidade.galeria.limiar_reentrada}, "
          f"lote {identidade.galeria.janela_lote_s:.0f}s)")
    print(f"Linha    : {linha.a} -> {linha.b}  (dentro = {linha.lado_dentro})")
    print(f"Início   : {inicio:%d/%m/%Y %H:%M:%S}")
    if pasta_recortes is not None:
        print(f"Recortes : {pasta_recortes}  (imagem de pessoa real — apague ao terminar)")
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
            janela=janela, trilha=trilha, escala_placar=escala_placar,
            identidade=identidade,
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

    g = identidade.galeria
    print()
    print(f"Quadros  : {resultado.quadros}  ({resultado.fps:.1f} q/s)")
    print(f"ENTRADAS : {resultado.entradas}")
    print(f"SAIDAS   : {resultado.saidas}")
    print(f"Saldo    : {resultado.entradas - resultado.saidas}")
    print(f"Pessoas  : {len(g.pessoas)} únicas  |  reentradas {g.reentradas}  "
          f"|  ainda dentro {len(g.dentro)}")
    print(f"Saídas   : atribuídas {g.atribuidas}  |  sem par {g.nao_atribuidas}  "
          f"|  fantasmas {g.fantasmas}  |  sem recorte {identidade.sem_recorte}")
    if remetente is not None:
        print(f"Enviados : {remetente.enviados} eventos  | em fila: {remetente.fila.tamanho}")
        if identidade.remetente is not None:
            print(f"           {identidade.pessoas_enviadas} pessoas, "
                  f"{identidade.vinculos_enviados} vínculos")
    if gravador is not None:
        print(f"Vídeo    : {gravador.caminho}")
    if trilha is not None:
        print(f"Trilha   : {trilha.caminho}  ({trilha.quadros} quadros)")
        print(f"           varra os limiares sem GPU: "
              f"python scripts/reprocessar_identidade.py {args.camera} --varredura")
    if pasta_recortes is not None:
        print(f"Recortes : {pasta_recortes}")
        print(f"           gere o gabarito: python scripts/rotular_pessoas.py --gerar "
              f"--camera {args.camera}")


if __name__ == "__main__":
    main()
