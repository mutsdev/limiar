"""Montagem da tarefa do Agendador — aspas, e o limite de 72 h que o XML zera."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from fluxo.operacao import agendador

PYTHON = Path(r"C:\Users\aluno\limiar\.venv\Scripts\python.exe")
SCRIPT = Path(r"C:\Users\aluno\Meus Projetos\limiar\scripts\rodar_tudo.py")
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _arvore(**kw) -> ET.Element:
    texto = agendador.xml_da_tarefa(PYTHON, SCRIPT, "entrada_real", r"LAB\aluno", **kw)
    return ET.fromstring(texto.encode("utf-16"))


class TestXml:
    def test_sem_limite_de_execucao_e_com_relancamento(self):
        raiz = _arvore()
        assert raiz.find("t:Settings/t:ExecutionTimeLimit", NS).text == "PT0S"
        assert raiz.find("t:Settings/t:RestartOnFailure/t:Interval", NS).text == "PT1M"
        assert raiz.find("t:Settings/t:DisallowStartIfOnBatteries", NS).text == "false"
        assert raiz.find("t:Settings/t:StopIfGoingOnBatteries", NS).text == "false"
        assert raiz.find("t:Settings/t:MultipleInstancesPolicy", NS).text == "IgnoreNew"

    def test_dispara_no_logon_do_usuario_sem_elevacao(self):
        raiz = _arvore()
        assert raiz.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text == r"LAB\aluno"
        assert raiz.find("t:Principals/t:Principal/t:RunLevel", NS).text == "LeastPrivilege"
        assert raiz.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"

    def test_comando_com_espaco_vai_entre_aspas_e_roda_na_raiz(self):
        raiz = _arvore()
        assert raiz.find("t:Actions/t:Exec/t:Command", NS).text == str(PYTHON)
        assert raiz.find("t:Actions/t:Exec/t:Arguments", NS).text == f'"{SCRIPT}" entrada_real'
        assert raiz.find("t:Actions/t:Exec/t:WorkingDirectory", NS).text == str(SCRIPT.parents[1])

    def test_tunel_e_host_sao_opcionais(self):
        raiz = _arvore(host_servico="0.0.0.0", tunel=True)
        argumentos = raiz.find("t:Actions/t:Exec/t:Arguments", NS).text
        assert argumentos.endswith("entrada_real --host-servico 0.0.0.0 --tunel")


class TestComandos:
    def test_criar_importa_o_xml_e_substitui_a_anterior(self):
        comando = agendador.comando_criar(Path(r"C:\x\tarefa.xml"))
        assert comando[:3] == ["schtasks", "/create", "/f"]
        assert comando[comando.index("/tn") + 1] == "Limiar"
        assert comando[comando.index("/xml") + 1] == r"C:\x\tarefa.xml"

    def test_plano_b_simples_mantem_as_aspas(self):
        comando = agendador.comando_criar_simples(PYTHON, SCRIPT, "entrada_real", tunel=True)
        assert comando[comando.index("/sc") + 1] == "ONLOGON"
        assert comando[comando.index("/tr") + 1] == f'"{PYTHON}" "{SCRIPT}" entrada_real --tunel'

    def test_remover_consultar_e_executar_usam_o_mesmo_nome(self):
        assert agendador.comando_remover()[-1] == "Limiar"
        assert "Limiar" in agendador.comando_consultar()
        assert agendador.comando_executar()[-1] == "Limiar"
