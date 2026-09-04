"""Partida no logon pelo Agendador de Tarefas do Windows.

Tarefa do próprio usuário não exige elevação — é o que permite instalar num
PC de laboratório sem admin. O comando é montado aqui, e não digitado à mão,
porque o erro clássico é o caminho com espaço sem aspas dentro do `/tr`: a
tarefa é criada, aparece na lista, e nunca sobe.

A tarefa é criada a partir de XML, e não de `/sc ONLOGON`, por causa de um
padrão do Windows que o `schtasks` simples não deixa mudar: **a tarefa é
encerrada depois de 72 horas** (`ExecutionTimeLimit`). Numa operação de
semanas, é a parada silenciosa do terceiro dia, sem nada no log. O XML zera
esse limite, manda relançar se o processo cair, e ignora bateria.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

NOME_TAREFA = "Limiar"


def linha_de_comando(python: Path, script: Path, *argumentos: str) -> str:
    """O que o Agendador vai executar. Caminhos sempre entre aspas."""
    return " ".join([f'"{python}"', f'"{script}"', *argumentos])


def argumentos_do_supervisor(
    camera: str, host_servico: str | None = None, tunel: bool = False
) -> list[str]:
    argumentos = [camera]
    if host_servico:
        argumentos += ["--host-servico", host_servico]
    if tunel:
        argumentos.append("--tunel")
    return argumentos


def xml_da_tarefa(
    python: Path,
    script: Path,
    camera: str,
    usuario: str,
    host_servico: str | None = None,
    tunel: bool = False,
    pasta_de_trabalho: Path | None = None,
) -> str:
    """O XML que `schtasks /create /xml` importa. Sem limite de execução."""
    argumentos = " ".join(
        [f'"{script}"', *argumentos_do_supervisor(camera, host_servico, tunel)]
    )
    pasta = pasta_de_trabalho or script.parent.parent
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Limiar: contagem de pessoas na porta. Sobe o supervisor no logon.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(usuario)}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(python))}</Command>
      <Arguments>{escape(argumentos)}</Arguments>
      <WorkingDirectory>{escape(str(pasta))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def comando_criar(arquivo_xml: Path, nome: str = NOME_TAREFA) -> list[str]:
    # /f substitui a tarefa se já existir: reinstalar não pode exigir remover antes.
    return ["schtasks", "/create", "/f", "/tn", nome, "/xml", str(arquivo_xml)]


def comando_criar_simples(
    python: Path,
    script: Path,
    camera: str,
    nome: str = NOME_TAREFA,
    host_servico: str | None = None,
    tunel: bool = False,
) -> list[str]:
    """O plano B, se o XML for recusado: funciona, mas herda o limite de 72 h."""
    return [
        "schtasks", "/create", "/f",
        "/tn", nome,
        "/sc", "ONLOGON",
        "/tr", linha_de_comando(
            python, script, *argumentos_do_supervisor(camera, host_servico, tunel)
        ),
    ]


def comando_remover(nome: str = NOME_TAREFA) -> list[str]:
    return ["schtasks", "/delete", "/f", "/tn", nome]


def comando_consultar(nome: str = NOME_TAREFA) -> list[str]:
    return ["schtasks", "/query", "/tn", nome, "/v", "/fo", "LIST"]


def comando_executar(nome: str = NOME_TAREFA) -> list[str]:
    """Dispara a tarefa agora, sem esperar o próximo logon."""
    return ["schtasks", "/run", "/tn", nome]
