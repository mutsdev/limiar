"""O relatório do dia: com dados traz os totais; sem dados, diz que não há."""

from datetime import date, datetime, timedelta

from fluxo.analise import relatorio
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, Origem
from fluxo.persistencia import repositorio

DIA = date(2026, 8, 25)
T0 = datetime(2026, 8, 25, 8, 0, 0, tzinfo=FUSO_LOCAL)


def _eventos():
    return [
        EventoCruzamento.criar("entrada_a", T0, Direcao.ENTRADA, track_id_local=1),
        EventoCruzamento.criar("entrada_a", T0 + timedelta(minutes=5), Direcao.ENTRADA,
                               track_id_local=2),
        EventoCruzamento.criar("entrada_a", T0 + timedelta(hours=3), Direcao.SAIDA,
                               track_id_local=3),
    ]


class TestComDados:
    def test_traz_totais_por_hora_e_execucao(self, banco):
        repositorio.inserir_eventos(banco, _eventos())
        eid = repositorio.registrar_execucao(
            banco, "entrada_a", "http://cam/stream", "yolo11n.pt", "bytetrack.yaml", 0.3, "abc1234"
        )
        banco.execute("UPDATE execucao SET inicio = ? WHERE id = ?", (T0.isoformat(), eid))
        banco.commit()

        texto = relatorio.gerar(banco, DIA, "entrada_a")
        assert "**Entradas** | **2**" in texto
        assert "**Saídas** | **1**" in texto
        assert "| 08h | 2 | 0 |" in texto
        assert "| 11h | 0 | 1 |" in texto
        assert "Hora de pico | 08h (2 entradas)" in texto
        assert "abc1234" in texto
        assert "Cruzamentos por track: 1.00" in texto
        assert "Máximo de **2** pessoas" in texto

    def test_sintetico_nao_entra(self, banco):
        repositorio.inserir_evento(banco, EventoCruzamento(
            camera_id="entrada_a", instante=T0, direcao=Direcao.ENTRADA,
            id_evento="sint-1", origem=Origem.SINTETICO,
        ))
        assert "Sem eventos" in relatorio.gerar(banco, DIA, "entrada_a")

    def test_todas_as_cameras(self, banco):
        repositorio.inserir_eventos(banco, _eventos())
        repositorio.inserir_evento(banco, EventoCruzamento.criar(
            "entrada_b", T0, Direcao.ENTRADA, track_id_local=9,
        ))
        texto = relatorio.gerar(banco, DIA, None)
        assert "todas as entradas" in texto
        assert "**Entradas** | **3**" in texto


class TestSemDados:
    def test_banco_vazio_nao_quebra(self, banco):
        texto = relatorio.gerar(banco, DIA, "entrada_a")
        assert texto.startswith("# Limiar — 25/08/2026 — entrada_a")
        assert "Sem eventos" in texto


class TestPeriodo:
    def test_recorta_pelo_instante_e_leva_o_nome(self, banco):
        repositorio.inserir_eventos(banco, _eventos())
        # Só os dois primeiros eventos (08:00 e 08:05) caem no período.
        periodo = repositorio.criar_periodo(
            banco, "Teste de campo", T0 - timedelta(minutes=1), T0 + timedelta(minutes=10),
            camera_id="entrada_a",
        )
        eid = repositorio.registrar_execucao(
            banco, "entrada_a", "http://cam/stream", "yolo11n.pt", "bytetrack.yaml", 0.3, "abc1234"
        )
        banco.execute("UPDATE execucao SET inicio = ? WHERE id = ?", (T0.isoformat(), eid))
        banco.commit()

        texto = relatorio.gerar_periodo(banco, periodo)
        assert texto.startswith("# Limiar — Teste de campo")
        assert "**Entradas** | **2**" in texto
        assert "**Saídas** | **0**" in texto
        assert "abc1234" in texto
        assert "Máximo de **2** pessoas" in texto
        assert "Por dia" not in texto  # um dia só

    def test_varios_dias_traz_a_tabela_por_dia(self, banco):
        eventos = _eventos() + [
            EventoCruzamento.criar("entrada_a", T0 + timedelta(days=1), Direcao.ENTRADA,
                                   track_id_local=7),
        ]
        repositorio.inserir_eventos(banco, eventos)
        periodo = repositorio.criar_periodo(banco, "Semana", T0, T0 + timedelta(days=2))
        texto = relatorio.gerar_periodo(banco, periodo)
        assert "## Por dia" in texto
        assert "| 25/08/2026 | 2 | 1 | +1 |" in texto
        assert "| 26/08/2026 | 1 | 0 | +1 |" in texto
        assert "Dias com movimento | 2" in texto

    def test_periodo_aberto_sem_eventos(self, banco):
        periodo = repositorio.criar_periodo(banco, "Lab", T0)
        texto = relatorio.gerar_periodo(banco, periodo)
        assert "em andamento" in texto
        assert "Sem eventos" in texto

    def test_slug(self):
        assert relatorio.slug("Teste de campo 03/09") == "teste-de-campo-03-09"
        assert relatorio.slug("Laboratório de física") == "laboratorio-de-fisica"
