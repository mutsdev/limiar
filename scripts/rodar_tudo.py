"""Sobe e mantém o Limiar inteiro: serviço, agente, painel — e o túnel.

    python scripts/rodar_tudo.py entrada_real
    python scripts/rodar_tudo.py entrada_real --tunel
    python scripts/rodar_tudo.py entrada_real --host-servico 0.0.0.0 --sem-painel

É o único processo que o Agendador de Tarefas precisa lançar no logon
(docs/operacao.md). Filho que morre é relançado com recuo exponencial; filho
vivo que parou de responder (sonda) é derrubado e relançado; o backup diário
do banco sai daqui; e a máquina é mantida acordada enquanto isto viver.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

# Este script NÃO chama garantir_venv: o os.execv trocaria o PID e confundiria
# quem o vigia. Ele só precisa do núcleo (que qualquer python com o pacote
# resolve) e lança os filhos com o interpretador certo do venv.
from fluxo import config, registro
from fluxo.ambiente import interpretador_do_projeto
from fluxo.operacao import energia, pulso, tunel
from fluxo.operacao.supervisor import ProcessoGerido, Supervisor
from fluxo.persistencia import backup

PAINEL = RAIZ / "src" / "fluxo" / "analise" / "painel.py"
PORTA_PAINEL = 8501

# Sem pulso por este tempo o agente é dado como travado. O pulso bate a cada
# 5 s mesmo com a câmera fora do ar; 3 min é folga para uma inferência lenta.
SILENCIO_MAXIMO_AGENTE_S = 180.0


def _sonda_http(url: str):
    def sonda() -> bool:
        import httpx

        try:
            return httpx.get(url, timeout=3.0).status_code == 200
        except Exception:
            return False

    return sonda


def main() -> None:
    p = argparse.ArgumentParser(description="Supervisor do Limiar")
    p.add_argument("camera", help="Id da câmera ao vivo em config/cameras.yaml")
    p.add_argument("--host-servico", default="127.0.0.1",
                   help="0.0.0.0 expõe o serviço na rede — só com CHAVE_API no .env")
    p.add_argument("--porta-servico", type=int, default=8000)
    p.add_argument("--sem-painel", action="store_true")
    p.add_argument("--tunel", action="store_true",
                   help="Sobe o cloudflared apontando para o painel e avisa a URL em URL_AVISO")
    p.add_argument("--janela", action="store_true",
                   help="O agente mostra a contagem numa janela (rodar_agente.py --janela)")
    p.add_argument("--escala", type=float, default=1.0, help="Tamanho da janela")
    p.add_argument("--fonte", default=None,
                   help="Sobrescreve a fonte da câmera só nesta execução (ensaio com ffmpeg)")
    args = p.parse_args()

    config.garantir_pastas()
    log = registro.configurar("supervisor", config.CAMINHO_LOGS / "supervisor.log")

    python = interpretador_do_projeto(exigir_visao=True)
    if python is None:
        python = Path(sys.executable)
        log.warning("Ambiente do projeto não encontrado; usando %s", python)

    scripts = RAIZ / "scripts"
    url_servico = f"http://127.0.0.1:{args.porta_servico}"
    # Todo filho roda com cwd na raiz do repositório: lançado pelo Agendador de
    # Tarefas o cwd é System32, e o ultralytics baixa `yolo11n.pt` no cwd —
    # ou falha por falta de permissão, na primeira execução da máquina nova.
    processos = [
        ProcessoGerido(
            "servico",
            [str(python), str(scripts / "rodar_servico.py"),
             "--host", args.host_servico, "--porta", str(args.porta_servico)],
            log=config.CAMINHO_LOGS / "servico.saida.log",
            cwd=RAIZ,
            sonda=_sonda_http(f"{url_servico}/saude"),
            sonda_apos_s=60.0,
        ),
        ProcessoGerido(
            "agente",
            [str(python), str(scripts / "rodar_agente.py"), args.camera]
            + (["--janela", "--escala", str(args.escala)] if args.janela else [])
            + (["--fonte", args.fonte] if args.fonte else []),
            log=config.CAMINHO_LOGS / "agente.saida.log",
            cwd=RAIZ,
            atraso_inicial_s=3.0,
            sonda=lambda: pulso.pulso_recente(
                pulso.arquivo_do_agente(args.camera), SILENCIO_MAXIMO_AGENTE_S
            ),
            # Subir torch + ultralytics num PC sem GPU leva minutos na primeira
            # vez (baixa o modelo). Antes disso, silêncio não é travamento.
            sonda_apos_s=300.0,
        ),
    ]
    if not args.sem_painel:
        # O streamlit entra direto, sem passar por rodar_painel.py: um
        # intermediário deixaria o streamlit órfão quando o supervisor
        # derrubasse o filho.
        processos.append(ProcessoGerido(
            "painel",
            [str(python), "-m", "streamlit", "run", str(PAINEL),
             "--server.address", "127.0.0.1", "--server.port", str(PORTA_PAINEL),
             "--server.headless", "true"],
            log=config.CAMINHO_LOGS / "painel.saida.log",
            cwd=RAIZ,
            atraso_inicial_s=5.0,
            sonda=_sonda_http(f"http://127.0.0.1:{PORTA_PAINEL}/_stcore/health"),
            sonda_apos_s=120.0,
        ))

    observadores = []
    if args.tunel:
        if args.sem_painel:
            sys.exit("--tunel expõe o painel; não faz sentido com --sem-painel.")
        exe = tunel.localizar_cloudflared()
        if exe is None:
            sys.exit("cloudflared não encontrado. Rode: python scripts/instalar_tunel.py")
        if not config.SENHA_PAINEL:
            sys.exit("Defina SENHA_PAINEL no .env antes de expor o painel por túnel.")
        log_tunel = config.CAMINHO_LOGS / "tunel.saida.log"
        processos.append(ProcessoGerido(
            "tunel",
            tunel.comando_quick_tunnel(exe, PORTA_PAINEL),
            log=log_tunel,
            cwd=RAIZ,
            atraso_inicial_s=10.0,
        ))
        observadores.append(tunel.AnunciadorDeTunel(
            log_tunel, config.URL_AVISO, registrador=log,
            arquivo_url=config.CAMINHO_LOGS / "tunel.url",
        ))
        if not config.URL_AVISO:
            log.warning("URL_AVISO vazio: a URL do túnel fica só em %s", log_tunel)

    supervisor = Supervisor(
        processos,
        log,
        tarefa_diaria=lambda: backup.backup_diario(
            config.CAMINHO_BANCO, config.CAMINHO_BACKUPS
        ),
        observadores=observadores,
    )

    if energia.manter_acordado():
        log.info("Máquina mantida acordada enquanto o supervisor viver.")
    log.info("Supervisor de pé: %s", ", ".join(p.nome for p in processos))
    try:
        supervisor.rodar()
    except KeyboardInterrupt:
        log.info("Encerrado pelo teclado.")


if __name__ == "__main__":
    main()
