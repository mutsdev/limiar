from datetime import date, datetime

import pytest

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, Origem
from fluxo.persistencia import repositorio
from fluxo.persistencia.repositorio import CameraDesconhecida


def evento(camera="entrada_a", h=8, m=0, direcao=Direcao.ENTRADA, track=1, dia=25):
    return EventoCruzamento.criar(
        camera,
        datetime(2026, 8, dia, h, m, 0, tzinfo=FUSO_LOCAL),
        direcao,
        track_id_local=track,
        confianca=0.9,
    )


class TestInsercao:
    def test_insere_e_le_de_volta(self, banco):
        assert repositorio.inserir_evento(banco, evento()) is True
        linhas = repositorio.consultar_eventos(banco)
        assert len(linhas) == 1
        assert linhas[0]["camera_id"] == "entrada_a"
        assert linhas[0]["direcao"] == "ENTRADA"
        assert linhas[0]["data_ref"] == "2026-08-25"

    def test_camera_desconhecida_e_recusada(self, banco):
        with pytest.raises(CameraDesconhecida):
            repositorio.inserir_evento(banco, evento(camera="porta_dos_fundos"))


class TestDeduplicacao:
    """O teste mais importante do módulo.

    Sem idempotência, uma reconexão de rede reenvia a fila e infla a contagem —
    e o erro é silencioso, porque o número continua parecendo plausível.
    """

    def test_o_mesmo_evento_duas_vezes_grava_uma_linha(self, banco):
        e = evento()
        assert repositorio.inserir_evento(banco, e) is True
        assert repositorio.inserir_evento(banco, e) is False
        assert len(repositorio.consultar_eventos(banco)) == 1

    def test_lote_repetido_nao_duplica(self, banco):
        lote = [evento(track=i) for i in range(10)]
        assert repositorio.inserir_eventos(banco, lote) == (10, 0)
        assert repositorio.inserir_eventos(banco, lote) == (0, 10)
        assert len(repositorio.consultar_eventos(banco)) == 10

    def test_eventos_diferentes_no_mesmo_segundo_coexistem(self, banco):
        repositorio.inserir_evento(banco, evento(track=1))
        repositorio.inserir_evento(banco, evento(track=2))
        assert len(repositorio.consultar_eventos(banco)) == 2


class TestFiltroDeOrigem:
    def test_consulta_padrao_esconde_sintetico(self, banco):
        real = evento(track=1)
        falso = EventoCruzamento(
            camera_id="entrada_a",
            instante=datetime(2026, 8, 25, 9, 0, tzinfo=FUSO_LOCAL),
            direcao=Direcao.ENTRADA,
            id_evento="sint-1",
            origem=Origem.SINTETICO,
        )
        repositorio.inserir_eventos(banco, [real, falso])

        assert len(repositorio.consultar_eventos(banco)) == 1
        assert len(repositorio.consultar_eventos(banco, origem=Origem.SINTETICO)) == 1
        assert len(repositorio.consultar_eventos(banco, origem=None)) == 2


class TestAgregacao:
    @pytest.fixture
    def povoado(self, banco):
        eventos = [
            evento(camera="entrada_a", h=8, track=1, direcao=Direcao.ENTRADA),
            evento(camera="entrada_a", h=8, track=2, direcao=Direcao.ENTRADA),
            evento(camera="entrada_a", h=8, track=3, direcao=Direcao.ENTRADA),
            evento(camera="entrada_a", h=18, track=4, direcao=Direcao.SAIDA),
            evento(camera="entrada_b", h=8, track=5, direcao=Direcao.ENTRADA),
            evento(camera="entrada_b", h=19, track=6, direcao=Direcao.SAIDA),
            evento(camera="entrada_a", h=8, track=7, direcao=Direcao.ENTRADA, dia=26),
        ]
        repositorio.inserir_eventos(banco, eventos)
        return banco

    def test_contagem_diaria(self, povoado):
        linhas = repositorio.contagem_diaria(povoado)
        totais = {(r["data_ref"], r["camera_id"], r["direcao"]): r["total"] for r in linhas}
        assert totais[("2026-08-25", "entrada_a", "ENTRADA")] == 3
        assert totais[("2026-08-25", "entrada_a", "SAIDA")] == 1
        assert totais[("2026-08-25", "entrada_b", "ENTRADA")] == 1
        assert totais[("2026-08-26", "entrada_a", "ENTRADA")] == 1

    def test_filtro_por_camera(self, povoado):
        linhas = repositorio.contagem_diaria(povoado, camera_id="entrada_b")
        assert {r["camera_id"] for r in linhas} == {"entrada_b"}

    def test_filtro_por_periodo(self, povoado):
        linhas = repositorio.contagem_diaria(
            povoado, data_inicio=date(2026, 8, 26), data_fim=date(2026, 8, 26)
        )
        assert {r["data_ref"] for r in linhas} == {"2026-08-26"}

    def test_contagem_horaria_extrai_a_hora(self, povoado):
        linhas = repositorio.contagem_horaria(povoado, camera_id="entrada_a")
        por_dia_e_hora = {
            (r["data_ref"], r["hora"], r["direcao"]): r["total"] for r in linhas
        }
        assert por_dia_e_hora[("2026-08-25", 8, "ENTRADA")] == 3
        assert por_dia_e_hora[("2026-08-25", 18, "SAIDA")] == 1
        assert por_dia_e_hora[("2026-08-26", 8, "ENTRADA")] == 1

    def test_contagem_horaria_separa_os_dias(self, povoado):
        """Duas horas iguais em dias diferentes são linhas diferentes.

        Se fossem somadas, a curva por hora do painel misturaria dias e o pico
        de um dia contaminaria o outro.
        """
        linhas = repositorio.contagem_horaria(povoado, camera_id="entrada_a")
        oito_entrada = [
            r for r in linhas if r["hora"] == 8 and r["direcao"] == "ENTRADA"
        ]
        assert len(oito_entrada) == 2
        assert {r["data_ref"] for r in oito_entrada} == {"2026-08-25", "2026-08-26"}


class TestExecucao:
    def test_registra_e_finaliza(self, banco):
        eid = repositorio.registrar_execucao(
            banco, "entrada_a", "video.mp4", "yolo11n.pt", "bytetrack", 0.3, "abc123"
        )
        repositorio.finalizar_execucao(banco, eid, quadros=1500, eventos=42)
        linha = banco.execute("SELECT * FROM execucao WHERE id = ?", (eid,)).fetchone()
        assert linha["quadros"] == 1500
        assert linha["eventos"] == 42
        assert linha["fim"] is not None
