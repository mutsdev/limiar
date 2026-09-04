"""Supervisor — relançamento, recuo, estabilidade e a tarefa diária.

Nenhum subprocesso real: o lançador e o relógio são falsos, e cada teste
avança o tempo à mão.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fluxo.operacao.supervisor import ProcessoGerido, Supervisor, rotacionar_se_grande

LOG = logging.getLogger("teste-supervisor")


class ProcessoFalso:
    _pid = 0

    def __init__(self):
        ProcessoFalso._pid += 1
        self.pid = ProcessoFalso._pid
        self.codigo = None
        self.terminado = False

    def poll(self):
        return self.codigo

    def morrer(self, codigo=1):
        self.codigo = codigo

    def terminate(self):
        self.terminado = True
        self.morrer(0)

    def wait(self, timeout=None):
        return self.codigo

    def kill(self):
        self.morrer(-9)


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def gerido(nome="p", **kw) -> ProcessoGerido:
    return ProcessoGerido(nome, ["python", "-c", "pass"], log=Path("nao-usado.log"), **kw)


def montar(processos, tarefa_diaria=None, hoje=None, observadores=None):
    relogio = Relogio()
    lancados = []

    def lancador(p):
        proc = ProcessoFalso()
        lancados.append(p.nome)
        return proc

    supervisor = Supervisor(
        processos, LOG, lancador=lancador, relogio=relogio,
        tarefa_diaria=tarefa_diaria, hoje=hoje or date.today,
        observadores=observadores,
    )
    return supervisor, relogio, lancados


class TestLancamento:
    def test_primeiro_passo_lanca_todos(self):
        processos = [gerido("a"), gerido("b")]
        supervisor, _, lancados = montar(processos)
        supervisor.passo()
        assert lancados == ["a", "b"]
        assert all(p.processo is not None for p in processos)

    def test_atraso_inicial_e_respeitado(self):
        p = gerido("painel", atraso_inicial_s=5.0)
        supervisor, relogio, lancados = montar([p])
        supervisor.passo()
        assert lancados == []
        relogio.t = 4.9
        supervisor.passo()
        assert lancados == []
        relogio.t = 5.0
        supervisor.passo()
        assert lancados == ["painel"]

    def test_lancador_que_falha_entra_no_recuo(self):
        p = gerido("a")
        relogio = Relogio()
        tentativas = []

        def lancador_quebrado(proc):
            tentativas.append(relogio.t)
            raise OSError("executável sumiu")

        supervisor = Supervisor([p], LOG, lancador=lancador_quebrado, relogio=relogio)
        supervisor.passo()
        relogio.t = 0.5
        supervisor.passo()  # antes do recuo de 1 s: não tenta
        relogio.t = 1.0
        supervisor.passo()
        assert tentativas == [0.0, 1.0]


class TestRelancamento:
    def test_morte_relanca_com_recuo_crescente(self):
        p = gerido("a", espera_inicial_s=1.0, espera_maxima_s=60.0)
        supervisor, relogio, lancados = montar([p])
        supervisor.passo()
        assert lancados == ["a"]

        p.processo.morrer()
        relogio.t = 10.0
        supervisor.passo()  # detecta a morte; próximo lançamento em 11.0
        assert lancados == ["a"]
        relogio.t = 11.0
        supervisor.passo()
        assert lancados == ["a", "a"]

        # Segunda morte logo em seguida: o recuo dobra.
        p.processo.morrer()
        relogio.t = 12.0
        supervisor.passo()
        relogio.t = 13.0
        supervisor.passo()  # 12 + 2 = 14: ainda não
        assert lancados == ["a", "a"]
        relogio.t = 14.0
        supervisor.passo()
        assert lancados == ["a", "a", "a"]

    def test_estabilidade_zera_o_recuo(self):
        p = gerido("a", espera_inicial_s=1.0, estavel_apos_s=300.0)
        supervisor, relogio, lancados = montar([p])
        supervisor.passo()
        p.processo.morrer()
        relogio.t = 1.0
        supervisor.passo()
        relogio.t = 2.0
        supervisor.passo()
        assert lancados == ["a", "a"]
        assert p.espera_atual_s == 1.0

        # Cinco minutos vivo: a próxima morte volta a esperar só 1 s.
        relogio.t = 302.0
        supervisor.passo()
        assert p.espera_atual_s == 0.0
        p.processo.morrer()
        relogio.t = 310.0
        supervisor.passo()
        relogio.t = 311.0
        supervisor.passo()
        assert lancados == ["a", "a", "a"]


class TestTarefaDiaria:
    def test_roda_uma_vez_por_dia(self):
        execucoes = []
        dia = [date(2026, 8, 31)]
        supervisor, relogio, _ = montar(
            [gerido("a")],
            tarefa_diaria=lambda: execucoes.append(1),
            hoje=lambda: dia[0],
        )
        supervisor.passo()
        supervisor.passo()
        assert len(execucoes) == 1
        dia[0] = date(2026, 9, 1)
        supervisor.passo()
        assert len(execucoes) == 2

    def test_falha_na_tarefa_nao_derruba_o_passo(self):
        def explode():
            raise RuntimeError("disco cheio")

        supervisor, _, lancados = montar([gerido("a")], tarefa_diaria=explode)
        supervisor.passo()  # não propaga
        assert lancados == ["a"]


class TestSonda:
    """Processo vivo para o `poll()` e morto para quem depende dele."""

    def _com_sonda(self, respostas, **kw):
        # A sonda devolve os itens em ordem; esgotada, repete o último.
        fila = list(respostas)

        def sonda():
            if len(fila) > 1:
                return fila.pop(0)
            return fila[0]

        p = gerido("agente", sonda=sonda, sonda_apos_s=100.0, sonda_intervalo_s=10.0, **kw)
        return p

    def test_nao_sonda_antes_do_periodo_de_graca(self):
        chamadas = []
        p = gerido("agente", sonda=lambda: chamadas.append(1) or True, sonda_apos_s=100.0)
        supervisor, relogio, _ = montar([p])
        supervisor.passo()
        relogio.t = 99.0
        supervisor.passo()
        assert chamadas == []
        relogio.t = 100.0
        supervisor.passo()
        assert chamadas == [1]

    def test_tres_falhas_seguidas_derrubam_e_relancam(self):
        p = self._com_sonda([False])
        supervisor, relogio, lancados = montar([p])
        supervisor.passo()
        primeiro = p.processo

        for t in (100.0, 110.0, 120.0):
            relogio.t = t
            supervisor.passo()
        assert primeiro.terminado, "o processo travado deveria ter sido derrubado"
        assert p.processo is None
        # Relança pelo recuo normal, como uma morte.
        relogio.t = 121.0
        supervisor.passo()
        assert lancados == ["agente", "agente"]
        assert p.falhas_sonda == 0

    def test_sonda_que_volta_a_responder_zera_as_falhas(self):
        p = self._com_sonda([False, False, True, False, False])
        supervisor, relogio, lancados = montar([p])
        supervisor.passo()
        for t in (100.0, 110.0, 120.0, 130.0, 140.0):
            relogio.t = t
            supervisor.passo()
        assert lancados == ["agente"]
        assert not p.processo.terminado

    def test_respeita_o_intervalo_entre_sondas(self):
        chamadas = []
        p = gerido("agente", sonda=lambda: chamadas.append(1) or True,
                   sonda_apos_s=0.0, sonda_intervalo_s=30.0)
        supervisor, relogio, _ = montar([p])
        supervisor.passo()
        # Primeira sonda em t=5; a próxima só 30 s depois dela.
        for t in (5.0, 10.0, 34.0):
            relogio.t = t
            supervisor.passo()
        assert len(chamadas) == 1
        relogio.t = 35.0
        supervisor.passo()
        assert len(chamadas) == 2

    def test_sonda_que_explode_conta_como_falha(self):
        def sonda():
            raise ConnectionError("recusado")

        p = gerido("agente", sonda=sonda, sonda_apos_s=0.0, sonda_intervalo_s=1.0)
        supervisor, relogio, _ = montar([p])
        supervisor.passo()
        relogio.t = 1.0
        supervisor.passo()
        assert p.falhas_sonda == 1


class TestObservadores:
    def test_rodam_a_cada_passo_e_erro_nao_derruba(self):
        vistos = []

        def explode():
            raise RuntimeError("túnel sumiu")

        supervisor, _, lancados = montar(
            [gerido("a")], observadores=[explode, lambda: vistos.append(1)]
        )
        supervisor.passo()
        supervisor.passo()
        assert vistos == [1, 1]
        assert lancados == ["a"]


class TestRotacaoDaSaida:
    def test_arquivo_grande_vira_geracao_anterior(self, tmp_path):
        log = tmp_path / "painel.saida.log"
        log.write_bytes(b"x" * 100)
        assert rotacionar_se_grande(log, limite_bytes=50)
        assert not log.exists()
        assert (tmp_path / "painel.saida.log.1").read_bytes() == b"x" * 100

    def test_pequeno_fica_e_inexistente_nao_quebra(self, tmp_path):
        log = tmp_path / "a.log"
        log.write_bytes(b"x" * 10)
        assert not rotacionar_se_grande(log, limite_bytes=50)
        assert log.exists()
        assert not rotacionar_se_grande(tmp_path / "nao-existe.log")


class TestEncerrar:
    def test_derruba_na_ordem_inversa(self):
        processos = [gerido("servico"), gerido("agente"), gerido("painel")]
        supervisor, _, _ = montar(processos)
        supervisor.passo()
        vivos = [p.processo for p in processos]

        ordem = []
        for p, proc in zip(processos, vivos, strict=True):
            original = proc.terminate
            proc.terminate = (lambda nome=p.nome, o=original: (ordem.append(nome), o())[1])
        supervisor.encerrar()
        assert ordem == ["painel", "agente", "servico"]
        assert all(proc.poll() is not None for proc in vivos)
