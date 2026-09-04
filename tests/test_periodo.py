"""Período de teste: rótulo sobre um intervalo, que não toca em evento nenhum."""

from datetime import date, datetime, timedelta

import pytest

from fluxo.analise import consultas
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.dominio.periodo import Periodo
from fluxo.persistencia import repositorio

T0 = datetime(2026, 9, 3, 15, 19, 39, tzinfo=FUSO_LOCAL)
T1 = datetime(2026, 9, 3, 18, 26, 41, tzinfo=FUSO_LOCAL)


class TestDominio:
    def test_datas_de_um_periodo_fechado(self):
        p = Periodo(1, "Teste", T0, T1)
        assert p.datas() == (date(2026, 9, 3), date(2026, 9, 3))
        assert not p.aberto

    def test_periodo_aberto_vai_ate_agora(self):
        p = Periodo(1, "Lab", T0)
        agora = datetime(2026, 9, 6, 9, 0, tzinfo=FUSO_LOCAL)
        assert p.datas(agora) == (date(2026, 9, 3), date(2026, 9, 6))
        assert p.aberto
        assert "em andamento" in p.rotulo()

    def test_contem(self):
        p = Periodo(1, "Teste", T0, T1)
        assert p.contem(T0 + timedelta(minutes=1))
        assert not p.contem(T0 - timedelta(seconds=1))
        assert not p.contem(T1 + timedelta(seconds=1))
        assert Periodo(1, "Lab", T0).contem(T1 + timedelta(days=30))


class TestRepositorio:
    def test_cria_lista_e_acha_por_nome(self, banco):
        p = repositorio.criar_periodo(banco, "Teste de campo 03/09", T0, T1, "entrada_a")
        assert p.id is not None
        assert repositorio.periodo_por_nome(banco, "Teste de campo 03/09") == p
        assert repositorio.listar_periodos(banco) == [p]

    def test_nome_repetido_e_recusado(self, banco):
        repositorio.criar_periodo(banco, "Teste", T0, T1)
        with pytest.raises(repositorio.PeriodoDuplicado):
            repositorio.criar_periodo(banco, "Teste", T0)

    def test_camera_desconhecida_e_recusada(self, banco):
        with pytest.raises(repositorio.CameraDesconhecida):
            repositorio.criar_periodo(banco, "Teste", T0, camera_id="nao_existe")

    def test_fim_antes_do_inicio_e_recusado(self, banco):
        with pytest.raises(ValueError):
            repositorio.criar_periodo(banco, "Teste", T1, T0)

    def test_instante_ingenuo_ganha_o_fuso_local(self, banco):
        p = repositorio.criar_periodo(banco, "Teste", T0.replace(tzinfo=None))
        assert p.inicio == T0
        assert repositorio.periodo_por_nome(banco, "Teste").inicio == T0

    def test_aberto_e_encerrar(self, banco):
        repositorio.criar_periodo(banco, "Antigo", T0 - timedelta(days=2), T0 - timedelta(days=1))
        lab = repositorio.criar_periodo(banco, "Lab", T1)
        assert repositorio.periodo_aberto(banco) == lab

        fechado = repositorio.encerrar_periodo(banco, "Lab", T1 + timedelta(hours=2))
        assert fechado.fim == T1 + timedelta(hours=2)
        assert repositorio.periodo_aberto(banco) is None

    def test_encerrar_sem_fim_usa_agora(self, banco):
        repositorio.criar_periodo(banco, "Lab", T1)
        antes = datetime.now(FUSO_LOCAL)
        fechado = repositorio.encerrar_periodo(banco, "Lab")
        assert fechado.fim is not None and fechado.fim >= antes

    def test_renomear(self, banco):
        p = repositorio.criar_periodo(banco, "Teste 1", T0, T1)
        novo = repositorio.renomear_periodo(banco, p.id, "Teste de campo 03/09")
        assert novo.nome == "Teste de campo 03/09"
        assert repositorio.periodo_por_nome(banco, "Teste 1") is None
        with pytest.raises(repositorio.PeriodoDesconhecido):
            repositorio.renomear_periodo(banco, "Teste 1", "x")

    def test_lista_do_mais_recente(self, banco):
        repositorio.criar_periodo(banco, "A", T0 - timedelta(days=3), T0 - timedelta(days=2))
        repositorio.criar_periodo(banco, "B", T0, T1)
        assert [p.nome for p in repositorio.listar_periodos(banco)] == ["B", "A"]

    def test_periodo_nao_mexe_em_evento(self, banco):
        e = EventoCruzamento.criar("entrada_a", T0, Direcao.ENTRADA, track_id_local=1)
        repositorio.inserir_evento(banco, e)
        repositorio.criar_periodo(banco, "Teste", T0, T1, "entrada_a")
        assert len(repositorio.consultar_eventos(banco)) == 1


class TestRecortar:
    def _eventos(self, banco):
        eventos = [
            EventoCruzamento.criar("entrada_a", T0 - timedelta(minutes=5), Direcao.ENTRADA,
                                   track_id_local=1),
            EventoCruzamento.criar("entrada_a", T0 + timedelta(minutes=5), Direcao.ENTRADA,
                                   track_id_local=2),
            EventoCruzamento.criar("entrada_a", T1, Direcao.SAIDA, track_id_local=3),
            EventoCruzamento.criar("entrada_a", T1 + timedelta(minutes=5), Direcao.SAIDA,
                                   track_id_local=4),
        ]
        repositorio.inserir_eventos(banco, eventos)
        return consultas.carregar_eventos(banco)

    def test_recorta_por_instante_com_fuso(self, banco):
        df = self._eventos(banco)
        dentro = consultas.recortar(df, "instante", T0, T1)
        assert sorted(dentro["track_id_local"]) == [2, 3]

    def test_sem_fim_vai_ate_o_ultimo(self, banco):
        df = self._eventos(banco)
        assert sorted(consultas.recortar(df, "instante", T0)["track_id_local"]) == [2, 3, 4]

    def test_linha_sem_instante_fica(self, banco):
        df = self._eventos(banco)
        df.loc[df["track_id_local"] == 4, "instante"] = None
        assert 4 in set(consultas.recortar(df, "instante", T0, T1)["track_id_local"])

    def test_vazio_continua_vazio(self, banco):
        assert consultas.recortar(consultas.carregar_eventos(banco), "instante", T0).empty
