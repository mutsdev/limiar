"""Painel web.

    python scripts/rodar_painel.py

É aqui que o valor do sistema fica visível: a série que hoje não existe.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

if __package__ in (None, ""):  # rodado direto pelo streamlit
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from fluxo import config
from fluxo.analise import consultas
from fluxo.dominio.evento import Origem
from fluxo.persistencia import repositorio

st.set_page_config(page_title="Limiar", page_icon="🚪", layout="wide")


@st.cache_data(ttl=30)
def _carregar(inicio: date, fim: date, camera: str | None, origem: str) -> pd.DataFrame:
    conn = repositorio.conectar()
    try:
        return consultas.carregar_eventos(conn, inicio, fim, camera, Origem(origem))
    finally:
        conn.close()


@st.cache_data(ttl=60)
def _cameras() -> list[str]:
    conn = repositorio.conectar()
    try:
        return [c["id"] for c in repositorio.listar_cameras(conn)]
    finally:
        conn.close()


st.title("Limiar")
st.caption(
    "Fluxo de pessoas nas entradas — porta, instante e direção. "
    "Sem imagem, sem rosto, sem nome."
)

with st.sidebar:
    st.header("Filtros")
    hoje = date.today()
    periodo = st.date_input(
        "Período", value=(hoje - timedelta(days=14), hoje), format="DD/MM/YYYY"
    )
    # O date_input devolve tupla com o intervalo, mas devolve data unica
    # enquanto o usuario ainda nao escolheu o segundo limite.
    intervalo = isinstance(periodo, tuple) and len(periodo) == 2
    inicio, fim = periodo if intervalo else (periodo, periodo)

    opcoes = ["(todas)"] + _cameras()
    escolha = st.selectbox("Entrada", opcoes)
    camera = None if escolha == "(todas)" else escolha

    origem = st.radio(
        "Origem dos dados",
        [Origem.VISAO.value, Origem.SINTETICO.value],
        help="VISAO veio de câmera. SINTETICO é simulação, para desenvolver sem hardware.",
    )

df = _carregar(inicio, fim, camera, origem)

if origem == Origem.SINTETICO.value:
    st.warning(
        "Exibindo **dados sintéticos**. Servem para desenvolver e demonstrar o painel "
        "sem câmera instalada, e não representam movimento real.",
        icon="⚠️",
    )

if df.empty:
    st.info(
        "Nenhum evento no período.\n\n"
        "- Para dados reais: `python scripts/processar_video.py --camera entrada_a`\n"
        "- Para simulação: `python scripts/simular_dia.py --dias 14` e escolha SINTETICO ao lado."
    )
    st.stop()

# ---------------------------------------------------------------- resumo
resumo = consultas.resumo_diario(df)
entradas = int(resumo["entradas"].sum())
saidas = int(resumo["saidas"].sum())
dias = int(resumo["data_ref"].nunique())
pico = consultas.pico_do_dia(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Entradas", f"{entradas:,}".replace(",", "."))
c2.metric("Saídas", f"{saidas:,}".replace(",", "."))
c3.metric("Média por dia", f"{entradas // dias:,}".replace(",", ".") if dias else "—")
c4.metric("Hora de pico", f"{pico[0]:02d}h" if pico else "—",
          f"{pico[1]} entradas" if pico else None)

saldo = entradas - saidas
if entradas and abs(saldo) > 0.10 * entradas:
    st.warning(
        f"Saldo do período: **{saldo:+d}**. Entradas e saídas deveriam quase fechar. "
        f"Um desvio grande indica passagens não detectadas — vale conferir o vídeo anotado.",
        icon="📐",
    )

st.divider()

# ---------------------------------------------------------------- gráficos
esq, dir_ = st.columns([3, 2])

with esq:
    st.subheader("Movimento por hora do dia")
    serie = consultas.serie_horaria(df).set_index("hora")
    st.bar_chart(serie[["entradas", "saidas"]], height=300)
    st.caption("Somado no período. É a curva que define escala de portaria e horário de limpeza.")

with dir_:
    st.subheader("Uso de cada entrada")
    comparativo = consultas.comparativo_portas(df)
    st.dataframe(
        comparativo.rename(columns={
            "camera_id": "Entrada", "total": "Passagens", "participacao": "% do total"
        }),
        hide_index=True, use_container_width=True,
    )
    st.caption("Desbalanceamento grande costuma ser sinalização mal resolvida.")

st.subheader("Volume por dia")
por_dia = resumo.groupby("data_ref")[["entradas", "saidas"]].sum()
st.line_chart(por_dia, height=280)

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Ocupação estimada ao longo do dia")
    dias_disponiveis = sorted(df["data_ref"].dt.date.unique(), reverse=True)
    dia = st.selectbox("Dia", dias_disponiveis, format_func=lambda d: d.strftime("%d/%m/%Y"))
    curva = consultas.ocupacao_do_dia(df, dia)
    if curva.empty:
        st.info("Sem eventos nesse dia.")
    else:
        st.line_chart(curva.set_index("instante")["ocupacao"], height=260)
        st.caption(
            "Entradas acumuladas menos saídas. É **estimativa**: uma saída não detectada "
            "mantém a curva alta pelo resto do dia."
        )

with col_b:
    st.subheader("Média por dia da semana")
    media = consultas.media_por_dia_da_semana(df)
    if media.empty:
        st.info("Sem dados suficientes.")
    else:
        st.bar_chart(media.set_index("nome")["media_entradas"], height=260)
        st.caption("Base para planejar evento, prova e escala em dia fraco.")

with st.expander("Eventos brutos"):
    st.dataframe(
        df[["instante", "camera_id", "direcao", "track_id_local", "confianca"]]
        .rename(columns={
            "instante": "Instante", "camera_id": "Entrada", "direcao": "Direção",
            "track_id_local": "Track", "confianca": "Confiança",
        }),
        hide_index=True, use_container_width=True, height=320,
    )
    st.caption(f"{len(df)} eventos. Banco: `{config.CAMINHO_BANCO}`")
