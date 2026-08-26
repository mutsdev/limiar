"""O painel roda sem estourar exceção.

Erro de Streamlit aparece dentro da página, não no código de status HTTP —
sem este teste, um painel quebrado passa por "no ar".
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, Origem
from fluxo.persistencia import repositorio

# O AppTest resolve caminho relativo contra o arquivo de teste, não contra
# a raiz do projeto. Absoluto evita a surpresa.
CAMINHO_PAINEL = str(
    Path(__file__).resolve().parents[1] / "src" / "fluxo" / "analise" / "painel.py"
)


def _eventos_recentes() -> list[EventoCruzamento]:
    """Eventos nos últimos dias, para caírem na janela padrão do painel."""
    hoje = date.today()
    eventos, track = [], 0
    for atras in (1, 2, 3):
        dia = hoje - timedelta(days=atras)
        for hora, direcao, camera in [
            (8, Direcao.ENTRADA, "entrada_a"),
            (9, Direcao.ENTRADA, "entrada_b"),
            (18, Direcao.SAIDA, "entrada_a"),
            (19, Direcao.SAIDA, "entrada_b"),
        ]:
            track += 1
            eventos.append(
                EventoCruzamento.criar(
                    camera,
                    datetime(dia.year, dia.month, dia.day, hora, 0, tzinfo=FUSO_LOCAL),
                    direcao,
                    track_id_local=track,
                    confianca=0.9,
                )
            )
    return eventos


@pytest.fixture(autouse=True)
def _sem_cache():
    """O cache do Streamlit atravessa testes e serviria dado de outro banco."""
    import streamlit as st

    st.cache_data.clear()
    yield
    st.cache_data.clear()


def test_painel_vazio_orienta_em_vez_de_quebrar(banco):
    app = AppTest.from_file(CAMINHO_PAINEL, default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    # Sem dado, o painel deve dizer o que fazer, não mostrar gráfico vazio.
    assert any("simular_dia" in i.value for i in app.info)


def test_painel_com_dados_monta_os_indicadores(banco):
    repositorio.inserir_eventos(banco, _eventos_recentes())
    app = AppTest.from_file(CAMINHO_PAINEL, default_timeout=60).run()

    assert not app.exception, [e.value for e in app.exception]
    rotulos = [m.label for m in app.metric]
    assert "Entradas" in rotulos
    assert "Saídas" in rotulos
    assert "Hora de pico" in rotulos

    entradas = next(m for m in app.metric if m.label == "Entradas")
    assert entradas.value == "6"  # 2 entradas/dia x 3 dias


def test_painel_avisa_quando_o_saldo_nao_fecha(banco):
    """Entradas muito acima das saídas indicam passagem perdida."""
    hoje = date.today()
    eventos = [
        EventoCruzamento.criar(
            "entrada_a",
            datetime(hoje.year, hoje.month, hoje.day, 8, 0, tzinfo=FUSO_LOCAL)
            - timedelta(days=1, seconds=i),
            Direcao.ENTRADA,
            track_id_local=i,
            confianca=0.9,
        )
        for i in range(20)
    ]
    repositorio.inserir_eventos(banco, eventos)
    app = AppTest.from_file(CAMINHO_PAINEL, default_timeout=60).run()

    assert not app.exception, [e.value for e in app.exception]
    assert any("Saldo do período" in w.value for w in app.warning)


def test_painel_marca_dado_sintetico(banco):
    sinteticos = [
        EventoCruzamento(
            camera_id="entrada_a",
            instante=datetime(2026, 8, 24, 8, 0, tzinfo=FUSO_LOCAL),
            direcao=Direcao.ENTRADA,
            id_evento=f"sint-{i}",
            origem=Origem.SINTETICO,
        )
        for i in range(5)
    ]
    repositorio.inserir_eventos(banco, sinteticos)

    app = AppTest.from_file(CAMINHO_PAINEL, default_timeout=60)
    app.run()
    app.radio[0].set_value(Origem.SINTETICO.value).run()

    assert not app.exception, [e.value for e in app.exception]
    assert any("sintéticos" in w.value for w in app.warning)
