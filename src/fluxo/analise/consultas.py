"""Agregações sobre os eventos.

Toda função filtra `origem=VISAO` por padrão. Dado sintético existe para
construir o painel antes de haver câmera, e não pode virar número de relatório
por descuido — por isso ver o sintético exige pedir explicitamente.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd

from fluxo.dominio.evento import Direcao, Origem

COLUNAS = [
    "id", "camera_id", "instante", "data_ref", "direcao",
    "track_id_local", "confianca", "origem",
]


def carregar_eventos(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
    origem: Origem | None = Origem.VISAO,
) -> pd.DataFrame:
    onde, params = [], []
    if data_inicio is not None:
        onde.append("data_ref >= ?")
        params.append(data_inicio.isoformat())
    if data_fim is not None:
        onde.append("data_ref <= ?")
        params.append(data_fim.isoformat())
    if camera_id is not None:
        onde.append("camera_id = ?")
        params.append(camera_id)
    if origem is not None:
        onde.append("origem = ?")
        params.append(origem.value)

    sql = f"SELECT {', '.join(COLUNAS)} FROM evento"
    if onde:
        sql += " WHERE " + " AND ".join(onde)
    sql += " ORDER BY instante"

    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        df["instante"] = pd.to_datetime(pd.Series(dtype="object"), utc=True)
        df["data_ref"] = pd.to_datetime(pd.Series(dtype="object"))
        return df

    df["instante"] = pd.to_datetime(df["instante"], format="ISO8601")
    df["data_ref"] = pd.to_datetime(df["data_ref"])
    df["hora"] = df["instante"].dt.hour
    df["dia_semana"] = df["data_ref"].dt.dayofweek
    return df


def _vazio(colunas: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=colunas)


def recortar(
    df: pd.DataFrame, coluna: str, inicio: datetime, fim: datetime | None = None
) -> pd.DataFrame:
    """Só as linhas cujo instante cai em [inicio, fim] — o recorte fino do período.

    Em pandas, e não em SQL, de propósito: o banco guarda o instante como
    texto ISO, e comparar texto só funciona enquanto todo registro tiver o
    mesmo offset. Comparar datetime com fuso é correto sempre. Linha sem
    instante (vínculo cujo evento ainda não chegou) fica.
    """
    if df.empty:
        return df
    serie = df[coluna]
    sem_instante = serie.isna()
    mascara = sem_instante | (serie >= inicio)
    if fim is not None:
        mascara &= sem_instante | (serie <= fim)
    return df[mascara]


def resumo_diario(df: pd.DataFrame) -> pd.DataFrame:
    """Entradas, saídas e saldo por dia e porta."""
    if df.empty:
        return _vazio(["data_ref", "camera_id", "entradas", "saidas", "saldo"])

    tabela = (
        df.pivot_table(
            index=["data_ref", "camera_id"],
            columns="direcao",
            values="id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
        .rename(columns={Direcao.ENTRADA.value: "entradas", Direcao.SAIDA.value: "saidas"})
    )
    for coluna in ("entradas", "saidas"):
        if coluna not in tabela:
            tabela[coluna] = 0
    tabela["saldo"] = tabela["entradas"] - tabela["saidas"]
    tabela.columns.name = None
    return tabela[["data_ref", "camera_id", "entradas", "saidas", "saldo"]]


def serie_horaria(df: pd.DataFrame) -> pd.DataFrame:
    """Entradas e saídas por hora do dia, somadas no período."""
    if df.empty:
        return _vazio(["hora", "entradas", "saidas"])

    tabela = (
        df.pivot_table(index="hora", columns="direcao", values="id",
                       aggfunc="count", fill_value=0)
        .rename(columns={Direcao.ENTRADA.value: "entradas", Direcao.SAIDA.value: "saidas"})
    )
    for coluna in ("entradas", "saidas"):
        if coluna not in tabela:
            tabela[coluna] = 0
    # Reindexar para 0..23 evita buraco no gráfico em hora sem movimento.
    tabela = tabela.reindex(range(24), fill_value=0).reset_index()
    tabela.columns.name = None
    return tabela[["hora", "entradas", "saidas"]]


def ocupacao_do_dia(df: pd.DataFrame, dia: date) -> pd.DataFrame:
    """Curva de ocupação acumulada ao longo de um dia.

    É estimativa, não medição: soma entradas e subtrai saídas. Se o contador
    perder uma saída, a curva fica alta pelo resto do dia — e é exatamente
    por isso que o saldo de fim de dia serve como verificação.
    """
    if df.empty:
        return _vazio(["instante", "ocupacao"])

    do_dia = df[df["data_ref"] == pd.Timestamp(dia)].sort_values("instante")
    if do_dia.empty:
        return _vazio(["instante", "ocupacao"])

    delta = do_dia["direcao"].map({Direcao.ENTRADA.value: 1, Direcao.SAIDA.value: -1})
    # `.values` numa coluna com fuso descarta o fuso e converte para UTC: o pico
    # aparecia três horas adiantado (16h42 virava 19h42). Reindexar preserva.
    return pd.DataFrame(
        {
            "instante": do_dia["instante"].reset_index(drop=True),
            "ocupacao": delta.cumsum().reset_index(drop=True),
        }
    )


def comparativo_portas(df: pd.DataFrame) -> pd.DataFrame:
    """Quanto do fluxo total passa por cada porta."""
    if df.empty:
        return _vazio(["camera_id", "total", "participacao"])

    tabela = df.groupby("camera_id")["id"].count().reset_index()
    tabela.columns = ["camera_id", "total"]
    total = tabela["total"].sum()
    tabela["participacao"] = (tabela["total"] / total * 100).round(1) if total else 0.0
    return tabela.sort_values("total", ascending=False)


NOMES_DIA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def media_por_dia_da_semana(df: pd.DataFrame) -> pd.DataFrame:
    """Média de entradas por dia da semana. A terça não é a sexta."""
    if df.empty:
        return _vazio(["dia_semana", "nome", "media_entradas"])

    entradas = df[df["direcao"] == Direcao.ENTRADA.value]
    if entradas.empty:
        return _vazio(["dia_semana", "nome", "media_entradas"])

    por_dia = entradas.groupby(["data_ref", "dia_semana"])["id"].count().reset_index()
    por_dia.columns = ["data_ref", "dia_semana", "entradas"]
    media = por_dia.groupby("dia_semana")["entradas"].mean().round(0).reset_index()
    media.columns = ["dia_semana", "media_entradas"]
    media["nome"] = media["dia_semana"].map(lambda d: NOMES_DIA[int(d)])
    return media[["dia_semana", "nome", "media_entradas"]].sort_values("dia_semana")


def pico_do_dia(df: pd.DataFrame) -> tuple[int, int] | None:
    """(hora, entradas) da hora mais movimentada. None se não houver dado."""
    serie = serie_horaria(df)
    if serie.empty or serie["entradas"].sum() == 0:
        return None
    linha = serie.loc[serie["entradas"].idxmax()]
    return int(linha["hora"]), int(linha["entradas"])


# --------------------------------------------------------------------------
# Etapa 2 — pessoas de sessão e vínculos
# --------------------------------------------------------------------------

COLUNAS_PESSOAS = [
    "id", "camera_id", "data_ref", "pseudonimo", "primeiro_visto", "ultimo_visto",
    "apelido", "entradas", "saidas",
]
COLUNAS_VINCULOS = [
    "id_evento", "camera_id", "data_ref", "similaridade", "atribuido", "metodo",
    "pseudonimo", "apelido", "instante", "direcao",
]


def carregar_pessoas(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
) -> pd.DataFrame:
    from fluxo.persistencia import repositorio

    linhas = repositorio.listar_pessoas(conn, data_inicio, data_fim, camera_id)
    df = pd.DataFrame([dict(linha) for linha in linhas], columns=COLUNAS_PESSOAS)
    if not df.empty:
        for coluna in ("primeiro_visto", "ultimo_visto"):
            df[coluna] = pd.to_datetime(df[coluna], format="ISO8601")
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def carregar_vinculos(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
) -> pd.DataFrame:
    from fluxo.persistencia import repositorio

    linhas = repositorio.listar_vinculos(conn, data_inicio, data_fim, camera_id)
    df = pd.DataFrame([dict(linha) for linha in linhas], columns=COLUNAS_VINCULOS)
    if not df.empty:
        # Vínculo cujo evento ainda não chegou fica sem instante: NaT.
        df["instante"] = pd.to_datetime(df["instante"], format="ISO8601", errors="coerce")
        df["data_ref"] = pd.to_datetime(df["data_ref"])
    return df


def permanencias(vinculos: pd.DataFrame) -> pd.DataFrame:
    """Entrada→saída de cada pseudônimo, em minutos. Mesma regra de reid.metricas."""
    from fluxo.reid import metricas

    colunas = ["pseudonimo", "apelido", "entrada", "saida", "minutos"]
    if vinculos.empty:
        return _vazio(colunas)
    com_evento = vinculos.dropna(subset=["instante", "direcao"])
    registros = [
        metricas.Registro(
            r.id_evento, r.instante.to_pydatetime(), Direcao(r.direcao),
            None if pd.isna(r.pseudonimo) else r.pseudonimo,
        )
        for r in com_evento.itertuples(index=False)
    ]
    apelidos = (
        com_evento.dropna(subset=["pseudonimo"]).groupby("pseudonimo")["apelido"].first()
    )
    linhas = [
        {
            "pseudonimo": p.pseudonimo,
            "apelido": apelidos.get(p.pseudonimo),
            "entrada": p.entrada,
            "saida": p.saida,
            "minutos": round(p.segundos / 60, 1),
        }
        for p in metricas.permanencias(registros)
    ]
    return pd.DataFrame(linhas, columns=colunas)


def resumo_identidade(pessoas: pd.DataFrame, vinculos: pd.DataFrame) -> dict:
    """Os números da aba Pessoas. Únicos são somados por dia: P1 de hoje não é o de ontem."""
    saidas = (
        vinculos[vinculos["direcao"] == Direcao.SAIDA.value] if not vinculos.empty else vinculos
    )
    sem_par = int((saidas["atribuido"] == 0).sum()) if not saidas.empty else 0
    perms = permanencias(vinculos)
    return {
        "unicos": int(pessoas.groupby("data_ref")["pseudonimo"].nunique().sum())
        if not pessoas.empty else 0,
        "reentradas": int((vinculos["metodo"] == "reentrada").sum()) if not vinculos.empty else 0,
        "saidas": int(len(saidas)),
        "sem_par": sem_par,
        "taxa_sem_par": (sem_par / len(saidas)) if len(saidas) else 0.0,
        "permanencias": int(len(perms)),
        "permanencia_media_min": float(perms["minutos"].mean()) if not perms.empty else 0.0,
    }
