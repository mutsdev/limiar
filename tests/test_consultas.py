"""Agregações checadas contra dados fixos e conhecidos."""

from datetime import date, datetime

import pandas as pd
import pytest

from fluxo.analise import consultas
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, Origem
from fluxo.persistencia import repositorio


def evento(camera, dia, hora, direcao, track, origem=Origem.VISAO):
    return EventoCruzamento.criar(
        camera,
        datetime(2026, 8, dia, hora, 0, 0, tzinfo=FUSO_LOCAL),
        direcao,
        track_id_local=track,
        confianca=0.9,
        origem=origem,
    )


@pytest.fixture
def povoado(banco):
    # 24/08 é segunda, 25/08 é terça.
    eventos = [
        evento("entrada_a", 24, 8, Direcao.ENTRADA, 1),
        evento("entrada_a", 24, 8, Direcao.ENTRADA, 2),
        evento("entrada_a", 24, 18, Direcao.SAIDA, 3),
        evento("entrada_b", 24, 9, Direcao.ENTRADA, 4),
        evento("entrada_a", 25, 8, Direcao.ENTRADA, 5),
        evento("entrada_a", 25, 19, Direcao.SAIDA, 6),
        # Sintético: precisa ficar de fora de tudo por padrão.
        evento("entrada_b", 25, 8, Direcao.ENTRADA, 7, Origem.SINTETICO),
    ]
    repositorio.inserir_eventos(banco, eventos)
    return banco


class TestCarregar:
    def test_esconde_sintetico_por_padrao(self, povoado):
        df = consultas.carregar_eventos(povoado)
        assert len(df) == 6
        assert set(df["origem"]) == {"VISAO"}

    def test_sintetico_sob_demanda(self, povoado):
        df = consultas.carregar_eventos(povoado, origem=Origem.SINTETICO)
        assert len(df) == 1

    def test_deriva_hora_e_dia_da_semana(self, povoado):
        df = consultas.carregar_eventos(povoado)
        primeira = df.iloc[0]
        assert primeira["hora"] == 8
        assert primeira["dia_semana"] == 0  # 24/08/2026 é segunda

    def test_filtro_por_periodo(self, povoado):
        df = consultas.carregar_eventos(
            povoado, data_inicio=date(2026, 8, 25), data_fim=date(2026, 8, 25)
        )
        assert len(df) == 2

    def test_banco_vazio_devolve_dataframe_vazio(self, banco):
        df = consultas.carregar_eventos(banco)
        assert df.empty


class TestResumoDiario:
    def test_conta_por_dia_e_porta(self, povoado):
        r = consultas.resumo_diario(consultas.carregar_eventos(povoado))
        seg_a = r[(r["data_ref"] == pd.Timestamp("2026-08-24")) & (r["camera_id"] == "entrada_a")]
        assert seg_a["entradas"].item() == 2
        assert seg_a["saidas"].item() == 1
        assert seg_a["saldo"].item() == 1

    def test_vazio_nao_quebra(self, banco):
        r = consultas.resumo_diario(consultas.carregar_eventos(banco))
        assert r.empty
        assert list(r.columns) == ["data_ref", "camera_id", "entradas", "saidas", "saldo"]


class TestSerieHoraria:
    def test_cobre_as_24_horas(self, povoado):
        s = consultas.serie_horaria(consultas.carregar_eventos(povoado))
        assert len(s) == 24
        assert list(s["hora"]) == list(range(24))

    def test_soma_no_periodo(self, povoado):
        s = consultas.serie_horaria(consultas.carregar_eventos(povoado))
        assert s.loc[s["hora"] == 8, "entradas"].item() == 3
        assert s.loc[s["hora"] == 18, "saidas"].item() == 1
        assert s.loc[s["hora"] == 12, "entradas"].item() == 0

    def test_pico(self, povoado):
        assert consultas.pico_do_dia(consultas.carregar_eventos(povoado)) == (8, 3)

    def test_pico_sem_dado_e_none(self, banco):
        assert consultas.pico_do_dia(consultas.carregar_eventos(banco)) is None


class TestOcupacao:
    def test_sobe_com_entrada_e_desce_com_saida(self, povoado):
        df = consultas.carregar_eventos(povoado)
        curva = consultas.ocupacao_do_dia(df, date(2026, 8, 24))
        assert list(curva["ocupacao"]) == [1, 2, 3, 2]

    def test_dia_sem_evento_devolve_vazio(self, povoado):
        df = consultas.carregar_eventos(povoado)
        assert consultas.ocupacao_do_dia(df, date(2026, 8, 30)).empty

    def test_instante_continua_no_fuso_local(self, povoado):
        # `.values` convertia para UTC calado: o pico de ocupação aparecia três
        # horas adiantado no relatório e no painel.
        df = consultas.carregar_eventos(povoado)
        curva = consultas.ocupacao_do_dia(df, date(2026, 8, 24))
        assert list(curva["instante"]) == list(
            df[df["data_ref"] == pd.Timestamp(date(2026, 8, 24))]
            .sort_values("instante")["instante"]
        )
        assert curva["instante"].dt.tz is not None


class TestComparativo:
    def test_participacao_soma_cem(self, povoado):
        c = consultas.comparativo_portas(consultas.carregar_eventos(povoado))
        assert c["participacao"].sum() == pytest.approx(100.0, abs=0.2)
        assert c.iloc[0]["camera_id"] == "entrada_a"


class TestDiaDaSemana:
    def test_nomeia_os_dias(self, povoado):
        m = consultas.media_por_dia_da_semana(consultas.carregar_eventos(povoado))
        nomes = dict(zip(m["dia_semana"], m["nome"], strict=True))
        assert nomes[0] == "segunda"
        assert nomes[1] == "terça"

    def test_media_de_entradas(self, povoado):
        m = consultas.media_por_dia_da_semana(consultas.carregar_eventos(povoado))
        # Segunda: 2 em entrada_a + 1 em entrada_b = 3 entradas naquele dia.
        assert m[m["dia_semana"] == 0]["media_entradas"].item() == 3
