"""O relatório de um dia — ou de um período de teste — em markdown.

É o que sai da máquina e vai para a mesa de quem decide. Por isso ele diz o
número E diz o que o número não é: estimativa sem contagem manual de
referência, câmera VGA, uma porta. Um relatório que só traz o total convida a
confiar nele mais do que ele merece.

Lê o banco; não escreve nele. Roda com o agente de pé.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd

from fluxo.analise import consultas
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.dominio.periodo import Periodo

LARGURA_BARRA = 24


def _execucoes_do_dia(conn: sqlite3.Connection, dia: date, camera_id: str | None) -> list:
    sql = "SELECT * FROM execucao WHERE substr(inicio, 1, 10) = ?"
    params: list[object] = [dia.isoformat()]
    if camera_id:
        sql += " AND camera_id = ?"
        params.append(camera_id)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", params)]


def _execucoes_do_periodo(conn: sqlite3.Connection, periodo: Periodo) -> list:
    """As execuções que tocam o período. Comparado em datetime, não em texto."""
    sql = "SELECT * FROM execucao"
    params: list[object] = []
    if periodo.camera_id:
        sql += " WHERE camera_id = ?"
        params.append(periodo.camera_id)
    achadas = []
    for r in conn.execute(sql + " ORDER BY id", params):
        inicio = datetime.fromisoformat(r["inicio"])
        fim = datetime.fromisoformat(r["fim"]) if r["fim"] else None
        if periodo.fim is not None and inicio > periodo.fim:
            continue
        if fim is not None and fim < periodo.inicio:
            continue
        achadas.append(dict(r))
    return achadas


def _duracao(inicio: str, fim: str | None) -> str:
    a = datetime.fromisoformat(inicio)
    b = datetime.fromisoformat(fim) if fim else datetime.now(FUSO_LOCAL)
    seg = int((b - a).total_seconds())
    texto = f"{seg // 3600}h{(seg % 3600) // 60:02d}m"
    return texto if fim else texto + " (em andamento)"


def _secao_execucoes(execucoes: list) -> list[str]:
    if not execucoes:
        return []
    linhas = [
        "## Execuções", "",
        "| # | câmera | início | duração | quadros | modelo | código |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in execucoes:
        inicio = datetime.fromisoformat(e["inicio"])
        linhas.append(
            f"| {e['id']} | {e['camera_id']} | {inicio:%H:%M:%S} | "
            f"{_duracao(e['inicio'], e['fim'])} | {e['quadros'] or '—'} | "
            f"{e['modelo']} | {e['versao_codigo'] or '—'} |"
        )
    return linhas + [""]


def _secao_totais(df: pd.DataFrame, com_data: bool) -> tuple[list[str], float]:
    """Totais e a taxa de cruzamentos por track (que o "Como ler" usa)."""
    resumo = consultas.resumo_diario(df)
    entradas = int(resumo["entradas"].sum())
    saidas = int(resumo["saidas"].sum())
    saldo = entradas - saidas
    pico = consultas.pico_do_dia(df)
    primeira = df["instante"].min()
    ultima = df["instante"].max()
    tracks = int(df["track_id_local"].nunique()) if df["track_id_local"].notna().any() else 0
    por_track = len(df) / tracks if tracks else 0.0
    hora = "%d/%m %H:%M:%S" if com_data else "%H:%M:%S"

    linhas = [
        "## Totais", "",
        "| | |", "|---|---|",
        f"| **Entradas** | **{entradas}** |",
        f"| **Saídas** | **{saidas}** |",
        f"| Saldo (dentro ao fim, se começou vazio) | {saldo:+d} |",
        f"| Primeira travessia | {primeira.strftime(hora)} |",
        f"| Última travessia | {ultima.strftime(hora)} |",
    ]
    if com_data:
        linhas.append(f"| Dias com movimento | {int(resumo['data_ref'].nunique())} |")
    if pico:
        linhas.append(f"| Hora de pico | {pico[0]:02d}h ({pico[1]} entradas) |")
    return linhas, por_track


def _secao_por_dia(df: pd.DataFrame) -> list[str]:
    resumo = consultas.resumo_diario(df)
    por_dia = resumo.groupby("data_ref")[["entradas", "saidas", "saldo"]].sum().reset_index()
    linhas = ["", "## Por dia", "", "| dia | entradas | saídas | saldo |", "|---|---|---|---|"]
    for _, r in por_dia.iterrows():
        linhas.append(
            f"| {r['data_ref']:%d/%m/%Y} | {int(r['entradas'])} | {int(r['saidas'])} | "
            f"{int(r['saldo']):+d} |"
        )
    return linhas


def _secao_por_hora(df: pd.DataFrame) -> list[str]:
    linhas = ["", "## Por hora", "", "| hora | entradas | saídas | |", "|---|---|---|---|"]
    serie = consultas.serie_horaria(df)
    serie = serie[(serie["entradas"] + serie["saidas"]) > 0]
    maior = int((serie["entradas"] + serie["saidas"]).max()) if not serie.empty else 1
    for _, r in serie.iterrows():
        n = int(r["entradas"] + r["saidas"])
        barra = "█" * max(1, round(LARGURA_BARRA * n / maior))
        linhas.append(
            f"| {int(r['hora']):02d}h | {int(r['entradas'])} | {int(r['saidas'])} | {barra} |"
        )
    return linhas


def _secao_ocupacao(df: pd.DataFrame, dia: date, com_data: bool) -> list[str]:
    curva = consultas.ocupacao_do_dia(df, dia)
    if curva.empty:
        return []
    i = curva["ocupacao"].idxmax()
    pico_oc = int(curva.loc[i, "ocupacao"])
    quando = curva.loc[i, "instante"]
    hora = "%d/%m %H:%M" if com_data else "%H:%M"
    return ["", "## Ocupação estimada", "",
            f"Máximo de **{pico_oc}** pessoas dentro às {quando.strftime(hora)}. "
            "Estimativa: entradas acumuladas menos saídas — uma saída perdida "
            "mantém a curva alta pelo resto do dia.", ""]


def _secao_como_ler(por_track: float, unidade: str) -> list[str]:
    return [
        "## Como ler", "",
        f"- **Cruzamentos por track: {por_track:.2f}** (ideal 1,00). Acima disso, a mesma "
        "pessoa foi contada mais de uma vez na mesma passagem.",
        f"- Não há contagem manual de referência para este {unidade}: o erro **não foi "
        "medido**. A meta declarada do projeto é erro ≤ 10 % por direção "
        "(`docs/avaliacao.md`).",
        "- Câmera VGA (640×480) numa porta só. O saldo deveria fechar perto de zero "
        "no fim do dia; um desvio grande é passagem não detectada, não gente que ficou.",
        "- Os dados são de câmera (`origem=VISAO`); nenhum evento sintético entra aqui.",
        "",
    ]


CABECALHO = (
    "Contagem de passagens por linha virtual: **porta, instante e direção**. "
    "Sem imagem, sem rosto, sem nome."
)


def gerar(conn: sqlite3.Connection, dia: date, camera_id: str | None = None) -> str:
    """Markdown do dia. Sem eventos, ainda devolve um relatório — dizendo isso."""
    df = consultas.carregar_eventos(conn, dia, dia, camera_id)
    execucoes = _execucoes_do_dia(conn, dia, camera_id)
    onde = camera_id or "todas as entradas"

    linhas = [f"# Limiar — {dia:%d/%m/%Y} — {onde}", "", CABECALHO, ""]
    linhas += _secao_execucoes(execucoes)

    if df.empty:
        linhas += ["## Sem eventos", "", "Nenhuma travessia registrada neste dia. "
                   "Se o agente esteve de pé, ou ninguém passou, ou a linha está fora do "
                   "caminho — confira `dados/saidas/<camera>_linha.png`.", ""]
        return "\n".join(linhas)

    totais, por_track = _secao_totais(df, com_data=False)
    linhas += totais
    linhas += _secao_por_hora(df)
    linhas += _secao_ocupacao(df, dia, com_data=False)
    linhas += [""] if linhas[-1] != "" else []
    linhas += _secao_como_ler(por_track, "dia")
    return "\n".join(linhas)


def gerar_periodo(conn: sqlite3.Connection, periodo: Periodo) -> str:
    """Markdown de um período de teste nomeado, de um ou vários dias."""
    inicio_d, fim_d = periodo.datas()
    df = consultas.carregar_eventos(conn, inicio_d, fim_d, periodo.camera_id)
    df = consultas.recortar(df, "instante", periodo.inicio, periodo.fim)
    execucoes = _execucoes_do_periodo(conn, periodo)
    onde = periodo.camera_id or "todas as entradas"
    varios_dias = inicio_d != fim_d

    linhas = [
        f"# Limiar — {periodo.nome}", "",
        f"{periodo.rotulo()} — {onde}.", "",
        CABECALHO, "",
    ]
    if periodo.observacao:
        linhas += [periodo.observacao, ""]
    linhas += _secao_execucoes(execucoes)

    if df.empty:
        linhas += ["## Sem eventos", "", "Nenhuma travessia registrada neste período. "
                   "Se o agente esteve de pé, ou ninguém passou, ou a linha está fora do "
                   "caminho — confira `dados/saidas/<camera>_linha.png`.", ""]
        return "\n".join(linhas)

    totais, por_track = _secao_totais(df, com_data=varios_dias)
    linhas += totais
    if varios_dias:
        linhas += _secao_por_dia(df)
    linhas += _secao_por_hora(df)
    if not varios_dias:
        linhas += _secao_ocupacao(df, inicio_d, com_data=False)
    linhas += [""] if linhas[-1] != "" else []
    linhas += _secao_como_ler(por_track, "período")
    return "\n".join(linhas)


def slug(nome: str) -> str:
    """Nome de arquivo a partir do nome: 'Teste de campo 03/09' -> teste-de-campo-03-09."""
    import re
    import unicodedata

    texto = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto or "periodo"
