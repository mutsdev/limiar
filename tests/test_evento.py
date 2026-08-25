from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fluxo.dominio.evento import (
    FUSO_LOCAL,
    Direcao,
    EventoCruzamento,
    Origem,
    data_de_referencia,
    montar_id_evento,
)


def _instante(ano=2026, mes=8, dia=25, h=14, m=3, s=22) -> datetime:
    return datetime(ano, mes, dia, h, m, s, tzinfo=FUSO_LOCAL)


class TestDataDeReferencia:
    def test_meio_do_dia(self):
        assert data_de_referencia(_instante()).isoformat() == "2026-08-25"

    def test_um_minuto_antes_da_meia_noite(self):
        assert data_de_referencia(_instante(h=23, m=59)).isoformat() == "2026-08-25"

    def test_um_minuto_depois_da_meia_noite(self):
        assert data_de_referencia(_instante(h=0, m=1)).isoformat() == "2026-08-25"

    def test_converte_de_outro_fuso(self):
        # 03:30 UTC é 00:30 em -03:00, ainda no dia 25.
        utc = datetime(2026, 8, 25, 3, 30, tzinfo=UTC)
        assert data_de_referencia(utc).isoformat() == "2026-08-25"

    def test_utc_antes_do_corte_cai_no_dia_anterior(self):
        # 02:00 UTC é 23:00 do dia 24 no fuso local.
        utc = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)
        assert data_de_referencia(utc).isoformat() == "2026-08-24"


class TestIdDeEvento:
    def test_e_deterministico(self):
        a = montar_id_evento("entrada_a", 42, Direcao.ENTRADA, _instante())
        b = montar_id_evento("entrada_a", 42, Direcao.ENTRADA, _instante())
        assert a == b

    def test_muda_com_a_direcao(self):
        a = montar_id_evento("entrada_a", 42, Direcao.ENTRADA, _instante())
        b = montar_id_evento("entrada_a", 42, Direcao.SAIDA, _instante())
        assert a != b

    def test_muda_com_a_camera(self):
        a = montar_id_evento("entrada_a", 42, Direcao.ENTRADA, _instante())
        b = montar_id_evento("entrada_b", 42, Direcao.ENTRADA, _instante())
        assert a != b

    def test_independe_do_fuso_em_que_foi_escrito(self):
        # O mesmo instante físico gera a mesma chave, venha em -03:00 ou em UTC.
        local = datetime(2026, 8, 25, 14, 3, 22, tzinfo=FUSO_LOCAL)
        utc = local.astimezone(UTC)
        assert montar_id_evento("a", 1, Direcao.ENTRADA, local) == montar_id_evento(
            "a", 1, Direcao.ENTRADA, utc
        )


class TestValidacao:
    def test_confianca_acima_de_um_e_recusada(self):
        with pytest.raises(ValidationError):
            EventoCruzamento(
                camera_id="entrada_a",
                instante=_instante(),
                direcao=Direcao.ENTRADA,
                confianca=1.4,
                id_evento="x",
            )

    def test_direcao_invalida_e_recusada(self):
        with pytest.raises(ValidationError):
            EventoCruzamento(
                camera_id="entrada_a",
                instante=_instante(),
                direcao="ENTRDA",  # erro de digitação
                id_evento="x",
            )

    def test_instante_sem_fuso_recebe_o_fuso_local(self):
        evento = EventoCruzamento(
            camera_id="entrada_a",
            instante=datetime(2026, 8, 25, 14, 3, 22),
            direcao=Direcao.ENTRADA,
            id_evento="x",
        )
        assert evento.instante.utcoffset() == timedelta(hours=-3)

    def test_origem_padrao_e_visao(self):
        evento = EventoCruzamento(
            camera_id="entrada_a",
            instante=_instante(),
            direcao=Direcao.ENTRADA,
            id_evento="x",
        )
        assert evento.origem is Origem.VISAO


class TestCriar:
    def test_deriva_a_chave_de_deduplicacao(self):
        evento = EventoCruzamento.criar(
            "entrada_a", _instante(), Direcao.ENTRADA, track_id_local=7, confianca=0.9
        )
        assert evento.id_evento == montar_id_evento(
            "entrada_a", 7, Direcao.ENTRADA, _instante()
        )
        assert evento.data_ref.isoformat() == "2026-08-25"
