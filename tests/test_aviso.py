"""Vigia — o que vira aviso no celular, e o que não vira.

Nada aqui usa rede: `enviar` é uma lambda que acumula numa lista, o relógio é
injetado e o "pulso de quadro" é um arquivo em `tmp_path` cuja data o teste
move à mão.

O que estes testes protegem, no fundo, é o silêncio: um alerta que se repete a
cada volta do supervisor é ignorado tão rápido quanto um que nunca chega.
"""

from __future__ import annotations

import logging
import os

import pytest

from fluxo.operacao.aviso import Vigia

LOG = logging.getLogger("teste-aviso")


class ProcessoFalso:
    """Só o que o Vigia lê: nome e os dois contadores públicos."""

    def __init__(self, nome="agente", lancamentos=1, falhas_sonda=0):
        self.nome = nome
        self.lancamentos = lancamentos
        self.falhas_sonda = falhas_sonda


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += s


def montar(processos=None, tmp_path=None, **kw):
    """Um Vigia com tudo injetado e a lista de envios ao lado."""
    enviados = []
    relogio = Relogio()
    # setdefault, e não valor fixo: assim o teste pode sobrescrever qualquer
    # um destes sem colidir com o default do helper.
    kw.setdefault("totais", lambda: (12, 9))
    kw.setdefault("arquivo_quadro", (tmp_path / "agente.quadro") if tmp_path else None)
    vigia = Vigia(
        processos if processos is not None else [ProcessoFalso()],
        "entrada_real",
        "https://ntfy.sh/limiar-x",
        enviar=lambda alvo, texto, **k: enviados.append(texto),
        registrador=LOG,
        relogio=relogio,
        **kw,
    )
    return vigia, relogio, enviados


def marcar_quadro(arquivo, idade_s=0.0):
    """O pulso de quadro batido `idade_s` segundos atrás."""
    import time

    arquivo.touch()
    quando = time.time() - idade_s
    os.utime(arquivo, (quando, quando))


class TestBatimento:
    def test_o_primeiro_sai_na_largada(self, tmp_path):
        # É a prova de que o canal funciona, dada enquanto você ainda está no
        # laboratório para consertar o tópico errado no .env.
        vigia, _, enviados = montar(tmp_path=tmp_path)
        vigia.observar()
        assert enviados == ["entrada_real: 12 entradas e 9 saídas hoje."]

    def test_sai_a_cada_seis_horas_e_nao_antes(self, tmp_path):
        vigia, relogio, enviados = montar(tmp_path=tmp_path, batimento_s=6 * 3600.0)

        def batimentos():
            # Filtra porque nestas seis horas o alerta de câmera muda também
            # sai — não há .quadro nenhum neste tmp_path.
            return [t for t in enviados if "entradas e" in t]

        vigia.observar()
        relogio.t = 6 * 3600.0 - 1
        vigia.observar()
        assert len(batimentos()) == 1, "ainda não deu a hora"
        relogio.t = 6 * 3600.0
        vigia.observar()
        assert len(batimentos()) == 2

    def test_banco_ilegivel_nao_derruba_a_vigilancia(self, tmp_path):
        def explode():
            raise OSError("banco travado")

        vigia, _, enviados = montar(tmp_path=tmp_path, totais=explode)
        assert vigia.observar() == []
        assert enviados == []


class TestRelancamento:
    def test_a_subida_inicial_nao_avisa(self, tmp_path):
        # Todo filho é "lançado" uma vez na largada. Avisar aí ensinaria você
        # a ignorar a notificação logo no primeiro minuto.
        p = ProcessoFalso(lancamentos=1)
        vigia, _, enviados = montar([p], tmp_path=tmp_path)
        vigia.observar()
        assert not [t for t in enviados if "relançado" in t]

    def test_relancamento_avisa_uma_vez_so(self, tmp_path):
        p = ProcessoFalso(lancamentos=1)
        vigia, relogio, enviados = montar([p], tmp_path=tmp_path)
        vigia.observar()
        enviados.clear()

        p.lancamentos = 2
        vigia.observar()
        assert enviados == ["agente caiu e foi relançado (nº 1)"]

        # O contador continua em 2 nas voltas seguintes: sem estado, o
        # supervisor chamando o observador a cada 5 s viraria spam.
        relogio.t = 10.0
        vigia.observar()
        assert len(enviados) == 1


class TestSonda:
    def test_avisa_na_primeira_falha_e_nao_nas_seguintes(self, tmp_path):
        p = ProcessoFalso(nome="painel")
        vigia, _, enviados = montar([p], tmp_path=tmp_path)
        vigia.observar()
        enviados.clear()

        for falhas in (1, 2, 3):
            p.falhas_sonda = falhas
            vigia.observar()
        assert enviados == ["painel está de pé mas não responde à sonda"]

    def test_sonda_que_volta_e_falha_de_novo_avisa_de_novo(self, tmp_path):
        p = ProcessoFalso(nome="painel")
        vigia, _, enviados = montar([p], tmp_path=tmp_path)
        vigia.observar()
        enviados.clear()

        p.falhas_sonda = 1
        vigia.observar()
        p.falhas_sonda = 0  # respondeu
        vigia.observar()
        p.falhas_sonda = 1  # caiu de novo
        vigia.observar()
        assert len(enviados) == 2


class TestCameraMuda:
    def test_a_carencia_de_partida_segura_o_alarme(self, tmp_path):
        # Sem quadro nenhum, mas o agente ainda está subindo o torch. Nada de
        # alarme antes de a carência passar.
        vigia, relogio, enviados = montar(tmp_path=tmp_path, carencia_s=600.0)
        vigia.observar()
        enviados.clear()
        relogio.t = 599.0
        vigia.observar()
        assert enviados == []

    def test_avisa_quando_para_de_chegar_quadro(self, tmp_path):
        vigia, relogio, enviados = montar(
            tmp_path=tmp_path, carencia_s=600.0, sem_quadro_maximo_s=900.0
        )
        marcar_quadro(tmp_path / "agente.quadro")
        vigia.observar()
        enviados.clear()

        relogio.t = 601.0
        marcar_quadro(tmp_path / "agente.quadro", idade_s=901.0)
        vigia.observar()
        assert len(enviados) == 1
        assert "Nenhum quadro da câmera entrada_real há mais de 15 min" in enviados[0]
        assert vigia.camera_muda

    def test_nao_repete_enquanto_continuar_muda(self, tmp_path):
        vigia, relogio, enviados = montar(tmp_path=tmp_path, carencia_s=0.0)
        marcar_quadro(tmp_path / "agente.quadro", idade_s=901.0)
        for t in (1.0, 2.0, 3.0):
            relogio.t = t
            vigia.observar()
        assert len([t for t in enviados if "Nenhum quadro" in t]) == 1

    def test_a_volta_da_camera_tambem_avisa(self, tmp_path):
        vigia, relogio, enviados = montar(tmp_path=tmp_path, carencia_s=0.0)
        marcar_quadro(tmp_path / "agente.quadro", idade_s=901.0)
        relogio.t = 1.0
        vigia.observar()
        enviados.clear()

        marcar_quadro(tmp_path / "agente.quadro")
        relogio.t = 2.0
        vigia.observar()
        assert enviados == ["A câmera entrada_real voltou a entregar quadros."]
        assert not vigia.camera_muda

    def test_arquivo_inexistente_conta_como_muda(self, tmp_path):
        # O agente nunca escreve o .quadro antes do primeiro quadro real:
        # ausência do arquivo é a resposta certa, não um caso de erro.
        vigia, relogio, enviados = montar(tmp_path=tmp_path, carencia_s=0.0)
        relogio.t = 1.0
        vigia.observar()
        assert any("Nenhum quadro" in t for t in enviados)


class TestEnvio:
    def test_sem_url_nao_envia_mas_continua_vigiando(self, tmp_path):
        enviados = []
        vigia = Vigia(
            [ProcessoFalso()], "entrada_real", "",
            enviar=lambda *a, **k: enviados.append(a),
            registrador=LOG, relogio=Relogio(),
            arquivo_quadro=tmp_path / "agente.quadro",
            totais=lambda: (1, 1),
        )
        assert vigia.observar() != [], "o aviso é decidido; só não é despachado"
        assert enviados == []

    def test_ntfy_fora_do_ar_nao_derruba_o_supervisor(self, tmp_path):
        def explode(*a, **k):
            raise ConnectionError("sem internet")

        vigia = Vigia(
            [ProcessoFalso()], "entrada_real", "https://ntfy.sh/x",
            enviar=explode, registrador=LOG, relogio=Relogio(),
            arquivo_quadro=tmp_path / "agente.quadro",
            totais=lambda: (1, 1),
        )
        assert vigia.observar() != []

    def test_e_chamavel_como_observador(self, tmp_path):
        vigia, _, enviados = montar(tmp_path=tmp_path)
        vigia()  # é assim que o Supervisor o invoca
        assert len(enviados) == 1


class TestTitulos:
    def test_sao_ascii(self, tmp_path):
        """Título vai em cabeçalho HTTP, que não carrega acento."""
        titulos = []
        p = ProcessoFalso(lancamentos=1)
        vigia = Vigia(
            [p], "entrada_real", "https://ntfy.sh/x",
            enviar=lambda alvo, texto, **k: titulos.append(k.get("titulo", "")),
            registrador=LOG, relogio=Relogio(),
            arquivo_quadro=tmp_path / "agente.quadro",
            carencia_s=0.0, totais=lambda: (1, 1),
        )
        vigia.observar()
        p.lancamentos, p.falhas_sonda = 2, 1
        vigia.observar()
        marcar_quadro(tmp_path / "agente.quadro")
        vigia.observar()

        assert len(titulos) >= 4
        for titulo in titulos:
            assert titulo.isascii(), titulo


@pytest.mark.parametrize("direcoes,esperado", [([], (0, 0)), (["ENTRADA"], (1, 0))])
def test_totais_do_dia_soma_por_direcao(banco, direcoes, esperado):
    from datetime import date, datetime, time, timedelta

    from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
    from fluxo.operacao.aviso import totais_do_dia
    from fluxo.persistencia import repositorio

    hoje = date.today()
    t0 = datetime.combine(hoje, time(9, 0), tzinfo=FUSO_LOCAL)
    eventos = [
        EventoCruzamento.criar(
            "entrada_a", t0 + timedelta(minutes=i), Direcao[d], track_id_local=i
        )
        for i, d in enumerate(direcoes)
    ]
    if eventos:
        repositorio.inserir_eventos(banco, eventos)
    assert totais_do_dia(banco, hoje, "entrada_a") == esperado
