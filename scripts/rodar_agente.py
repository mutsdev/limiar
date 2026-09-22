"""Roda a contagem contínua sobre uma câmera ao vivo, sem barra de progresso.

    python scripts/rodar_agente.py entrada_real
    python scripts/rodar_agente.py entrada_real --janela --escala 1.5
    python scripts/rodar_agente.py entrada_real --identificar --clipes

É o irmão 24h de processar_video.py: fonte resiliente (reconecta sozinha com
recuo), log em arquivo com rotação, envio sempre ligado. `--janela` mostra a
contagem numa janela sem abrir mão disso: fechar a janela (ou `q`) reabre em
seguida, e a contagem não para — os totais vivem fora do laço.
Para calibrar ou depurar, use processar_video.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import garantir_venv, normalizar_fonte

garantir_venv()

# Sem timeout, um RTSP que congela deixa o `read()` preso para sempre dentro do
# ffmpeg — nem o watchdog da FonteViva alcança, porque fechar a captura não
# interrompe a chamada. Precisa estar no ambiente ANTES do primeiro capture.
# Valores em microssegundos (10 s).
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rw_timeout;10000000|stimeout;10000000"
)

from fluxo import config, registro
from fluxo.agente import processador
from fluxo.agente.fila_local import FilaLocal
from fluxo.agente.remetente import Remetente
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, data_de_referencia
from fluxo.operacao import descoberta
from fluxo.operacao.pulso import Pulso, arquivo_de_quadro, arquivo_do_agente
from fluxo.visao import clipes
from fluxo.visao.fonte_viva import ConfigFonteViva, FonteViva
from fluxo.visao.quadro_vivo import PublicadorDeQuadro
from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas

# Erro fora da fonte (modelo, disco, bug) não melhora com relançamento
# imediato; a espera evita um laço quente de crash.
ESPERA_APOS_ERRO_S = 30.0
BATIMENTO_S = 3600.0
# Dez minutos sem quadro num endereço http: a placa pode ter reiniciado com
# outro IP (DHCP). A fonte desiste, e o agente procura a câmera na rede.
DESISTIR_APOS_S = 600.0


def _fonte_ao_vivo(fonte_str: str | int) -> bool:
    if isinstance(fonte_str, int):
        return True
    return str(fonte_str).startswith(("rtsp://", "http://", "https://"))


def _e_http(fonte_str: str | int) -> bool:
    return isinstance(fonte_str, str) and fonte_str.startswith(("http://", "https://"))


def _reencontrar_camera(camera_id: str, fonte_atual: str, persistir: bool, log) -> str | None:
    """Varre a rede local atrás de UMA câmera MJPEG em outro endereço.

    Uma só, de propósito: com duas placas na rede, trocar às cegas contaria a
    porta errada — pior que não contar. Nesse caso fica como está e loga.
    """
    try:
        redes = descoberta.redes_para_varrer(descoberta.ips_locais())
        candidatos: list[str] = []
        for rede in redes:
            candidatos += [ip for ip in descoberta.varrer(rede) if ip not in candidatos]
        cameras = descoberta.confirmar(candidatos)
    except Exception:
        log.exception("Varredura da rede falhou")
        return None
    urls = [descoberta.url_do_stream(ip) for ip in cameras]
    if len(urls) != 1:
        log.warning("Varredura achou %d câmera(s) (%s); mantendo %s",
                    len(urls), ", ".join(urls) or "nenhuma", fonte_atual)
        return None
    nova = urls[0]
    if nova == fonte_atual:
        log.info("A câmera continua em %s; era a rede, não o endereço.", nova)
        return None
    log.warning("Câmera reencontrada: %s -> %s", fonte_atual, nova)
    if persistir:
        # Grava no YAML para o próximo relançamento já nascer certo. Não
        # grava quando a fonte veio de --fonte: aquela era só desta execução.
        try:
            cameras_yaml = config.carregar_cameras()
            cameras_yaml[camera_id]["fonte"] = nova
            config.salvar_cameras(cameras_yaml)
        except Exception:
            log.exception("Não consegui gravar o endereço novo em %s", config.ARQUIVO_CAMERAS)
    return nova


def main() -> None:
    p = argparse.ArgumentParser(description="Agente de contagem contínua do Limiar")
    p.add_argument("camera", help="Id da câmera em config/cameras.yaml")
    p.add_argument("--fonte", default=None, help="Sobrescreve a fonte do YAML")
    p.add_argument("--janela", action="store_true",
                   help="Mostra a contagem numa janela. Fechá-la reabre em seguida; "
                        "a contagem não para.")
    p.add_argument("--escala", type=float, default=1.0,
                   help="Tamanho da janela (ex.: 1.5). Só afeta a exibição.")
    p.add_argument("--sem-quadro-vivo", action="store_true",
                   help="Não publica o último quadro anotado para a aba Ao vivo do painel")
    p.add_argument("--identificar", action="store_true",
                   help="Etapa 2: re-identificação anônima (pseudônimos do dia, sem rosto). "
                        "Sem a flag, a contagem é idêntica à de sempre.")
    p.add_argument("--clipes", action="store_true",
                   help="Grava ~12 s de vídeo anotado em volta de cada dúvida, em "
                        "dados/revisao/, para julgar na aba Revisão. É imagem de pessoa "
                        "(PROJETO §16.2): só em validação, com autorização; some em 48 h.")
    args = p.parse_args()

    config.garantir_pastas()
    # Primeira prova de vida antes de qualquer coisa pesada: o supervisor só
    # começa a sondar minutos depois, mas o arquivo já existe.
    batida = Pulso(arquivo_do_agente(args.camera))
    batida.bater()
    # O de quadro NÃO é batido aqui de propósito: enquanto nenhum quadro
    # tiver chegado, a ausência do arquivo é a resposta certa.
    batida_quadro = Pulso(arquivo_de_quadro(args.camera))
    cameras = config.carregar_cameras()
    pipeline = config.carregar_pipeline()

    if args.camera not in cameras:
        sys.exit(f"Câmera '{args.camera}' não existe em {config.ARQUIVO_CAMERAS}.")
    camera = cameras[args.camera]

    fonte_str = args.fonte if args.fonte is not None else camera.get("fonte")
    if not fonte_str and fonte_str != 0:
        sys.exit(f"Câmera '{args.camera}' não tem fonte. Passe --fonte.")
    fonte_str = normalizar_fonte(fonte_str)
    if not _fonte_ao_vivo(fonte_str):
        sys.exit(
            f"'{fonte_str}' é arquivo, e arquivo acaba — o agente 24h só faz\n"
            f"sentido com stream (rtsp/http) ou webcam. Para processar arquivo:\n"
            f"  python scripts/processar_video.py {args.camera}"
        )

    log = registro.configurar(
        f"agente.{args.camera}", config.CAMINHO_LOGS / f"agente_{args.camera}.log"
    )

    linha = LinhaDeContagem.de_config(args.camera, camera, pipeline)
    cfg_visao = ConfigVisao.de_pipeline(pipeline)
    rastreador = RastreadorPessoas(cfg_visao)

    fila = FilaLocal(config.CAMINHO_DADOS / "fila" / f"{args.camera}.jsonl")
    remetente = Remetente(config.URL_SERVICO, fila, chave=config.CHAVE_API)
    if not remetente.servico_no_ar():
        log.warning(
            "Serviço fora do ar em %s; eventos irão para a fila local até ele voltar.",
            config.URL_SERVICO,
        )

    publicador = None
    if not args.sem_quadro_vivo:
        publicador = PublicadorDeQuadro(config.CAMINHO_QUADROS / f"{args.camera}.jpg")

    # Fora do laço, como a linha: a FonteViva é recriada a cada volta, e a
    # galeria tem de sobreviver a isso — quem está dentro continua dentro.
    identidade = None
    limiares_reid: dict[str, float] = {}
    if args.identificar:
        from fluxo.agente.identidade import Identidade
        from fluxo.dominio.identidade import Vinculo
        from fluxo.reid.galeria import Galeria
        from fluxo.visao.aparencia import ConfigAparencia, Extrator

        remetente.fila_vinculos = FilaLocal(
            config.CAMINHO_DADOS / "fila" / f"{args.camera}.vinculos.jsonl", modelo=Vinculo
        )
        cfg_reid = ConfigAparencia.de_pipeline(pipeline, pasta_modelos=config.CAMINHO_MODELOS)
        galeria = Galeria.de_pipeline(pipeline)
        hoje = data_de_referencia(datetime.now(FUSO_LOCAL))
        n = galeria.semear(remetente.pessoas_do_dia(args.camera, hoje))
        log.info("Identidade retomada: %d pessoa(s) de hoje, próximo P%d", n, galeria.proximo)
        if n == 0 and not remetente.servico_no_ar():
            # ponytail: aceito. rodar_tudo sobe o serviço antes do agente, e o
            # torch leva minutos para carregar; o caso real é raro.
            log.warning(
                "Serviço fora do ar no arranque: a numeração recomeça em P1 e pode "
                "colidir com a de hoje."
            )
        identidade = Identidade(
            camera_id=args.camera,
            extrator=Extrator(cfg_reid),
            galeria=galeria,
            recortes_por_track=cfg_reid.recortes_por_track,
            intervalo_recorte_quadros=cfg_reid.intervalo_recorte_quadros,
            esquecer_apos_quadros=linha.quadros_ate_esquecer,
            remetente=remetente,
            registrador=log,
            guardar_decisoes=False,
        )
        limiares_reid = {"saida": galeria.limiar_saida, "reentrada": galeria.limiar_reentrada}
        remetente.drenar_vinculos()

    # Clipes velhos somem mesmo sem --clipes: os de uma execução anterior não
    # podem depender de alguém subir o agente com a flag de novo.
    clipes.purgar_clipes(config.CAMINHO_REVISAO)

    fonte_atual: list[FonteViva | None] = [None]

    def batimento() -> None:
        # Uma linha por hora no log é a evidência de vida: sem ela, "nenhum
        # evento" e "processo travado" seriam indistinguíveis à distância.
        while True:
            time.sleep(BATIMENTO_S)
            fonte = fonte_atual[0]
            log.info(
                "Batimento: entradas=%d saidas=%d fila_local=%d reconexoes=%s%s",
                linha.entradas, linha.saidas, fila.tamanho,
                fonte.reconexoes if fonte is not None else "-",
                f"  {identidade.placar()}" if identidade is not None else "",
            )
            apagados = clipes.purgar_clipes(config.CAMINHO_REVISAO)
            if apagados:
                log.info("Clipes de dúvida expirados apagados: %d arquivo(s)", apagados)

    threading.Thread(target=batimento, daemon=True, name="batimento").start()

    log.info(
        "Agente iniciando: camera=%s fonte=%s modelo=%s dispositivo=%s",
        args.camera, fonte_str, cfg_visao.modelo, rastreador.dispositivo,
    )

    while True:
        cfg_fonte = ConfigFonteViva(
            desistir_apos_s=DESISTIR_APOS_S if _e_http(fonte_str) else None
        )
        fonte = FonteViva(
            fonte_str, config=cfg_fonte, registrador=log,
            pulso=batida.bater, pulso_quadro=batida_quadro.bater,
        )
        fonte_atual[0] = fonte
        janela = None
        if args.janela:
            from fluxo.visao.anotador import JanelaAoVivo

            janela = JanelaAoVivo(f"Limiar - {args.camera}", fonte.fps, 1.0, args.escala)
        execucao_id = remetente.abrir_execucao(
            args.camera, str(fonte_str), cfg_visao.modelo,
            cfg_visao.tracker, cfg_visao.confianca_minima,
            processador.versao_do_codigo(),
        )
        gravador_duvidas = None
        if args.clipes:
            # Dentro do laço: largura, altura e fps vêm desta FonteViva.
            hoje = data_de_referencia(datetime.now(FUSO_LOCAL))
            gravador_duvidas = clipes.GravadorDeDuvidas(
                config.CAMINHO_REVISAO / hoje.isoformat() / args.camera, args.camera,
                fonte.fps, fonte.largura, fonte.altura,
                params={k: pipeline.get(k, {}) for k in ("contagem", "deteccao", "reid")},
                limiares=limiares_reid,
            )
        quadros = 0
        espera = ESPERA_APOS_ERRO_S
        try:
            resultado = processador.processar(
                fonte, rastreador, linha, remetente,
                mostrar_progresso=False, registrador=log, guardar_eventos=False,
                janela=janela,
                escala_placar=1.0 / args.escala if args.escala < 1.0 else 1.0,
                publicador=publicador,
                identidade=identidade,
                clipes=gravador_duvidas,
            )
            quadros = resultado.quadros
            if fonte.desistiu:
                # Dez minutos sem quadro: talvez a placa esteja em outro IP.
                # Achou uma, troca; não achou, volta a insistir no mesmo.
                nova = _reencontrar_camera(
                    args.camera, str(fonte_str), persistir=args.fonte is None, log=log,
                )
                if nova is not None:
                    fonte_str = nova
                espera = 1.0
            elif janela is not None:
                # Fechar a janela é o jeito normal de o laço terminar com ela.
                # Reabre já: cada segundo parado é gente passando sem contar.
                log.info("Janela fechada; reabrindo. A contagem continua.")
                espera = 1.0
            else:
                # A FonteViva só termina por fechar() ou desistindo; chegar
                # aqui sem nenhum dos dois é anomalia.
                log.error("Laço de contagem terminou sozinho; reiniciando.")
        except KeyboardInterrupt:
            log.info("Interrompido pelo teclado; encerrando.")
            break
        except Exception:
            log.exception("Erro no laço de contagem; reinício em %.0fs", ESPERA_APOS_ERRO_S)
        finally:
            fonte_atual[0] = None
            fonte.fechar()
            if janela is not None:
                janela.fechar()
            if execucao_id is not None:
                remetente.fechar_execucao(
                    execucao_id, quadros, linha.entradas + linha.saidas
                )
        time.sleep(espera)


if __name__ == "__main__":
    main()
