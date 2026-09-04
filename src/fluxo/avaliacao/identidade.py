"""Reconta uma trilha/2 com a galeria — sem GPU, quantas vezes for preciso.

A visão rodou uma vez e deixou na trilha os rastros E a assinatura de quem
cruzou. Aqui a contagem passa de novo pela MESMA `LinhaDeContagem` e cada
evento leva a assinatura gravada para a MESMA `Galeria` — só que agora com
limiares diferentes, em milissegundos. É como o limiar deixa de ser palpite.

Vale o que vale para `trilhas.contar`: se este replay não desse o mesmo que
o agente ao vivo, todo número medido aqui descreveria um sistema que não
existe. O caminho é o mesmo de propósito.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable
from pathlib import Path

from fluxo.avaliacao.trilhas import Trilha
from fluxo.dominio.evento import Direcao
from fluxo.reid import metricas
from fluxo.reid.galeria import Decisao, Galeria


def recontar(trilha: Trilha, linha, galeria: Galeria) -> tuple[list, list[Decisao]]:
    """Passa a trilha pela linha e pela galeria. Devolve (eventos, decisões).

    Evento cujo track não tem assinatura na trilha (cruzou antes de ser
    recortado) conta normalmente e não gera decisão — igual ao vivo.
    """
    eventos = []
    decisoes: list[Decisao] = []
    for quadro, instante, rastros in trilha.quadros:
        decisoes.extend(galeria.preparar(instante))
        novos = linha.processar(quadro, instante, rastros)
        eventos.extend(novos)
        for e in novos:
            assinatura = trilha.assinatura_de(e.track_id_local, quadro)
            if assinatura is None:
                continue
            if e.direcao is Direcao.ENTRADA:
                decisoes.append(
                    galeria.entrar(e.id_evento, e.track_id_local, assinatura, e.instante)
                )
            else:
                galeria.sair(e.id_evento, e.track_id_local, assinatura, e.instante)
    if trilha.quadros:
        decisoes.extend(galeria.fechar(trilha.quadros[-1][1]))
    decisoes.sort(key=lambda d: d.instante)
    return eventos, decisoes


def registros_de(decisoes: Iterable[Decisao]) -> list[metricas.Registro]:
    return [
        metricas.Registro(d.id_evento, d.instante, d.direcao, d.pseudonimo)
        for d in decisoes
    ]


# Colunas do CSV de gabarito. O João Pedro preenche só a última.
COLUNAS_GABARITO = [
    "id_evento", "instante", "direcao", "pseudonimo", "metodo", "arquivo", "apelido_real",
]


def carregar_gabarito(caminho: str | Path) -> dict[str, str]:
    """id_evento -> apelido_real, ignorando linhas em branco."""
    gabarito: dict[str, str] = {}
    with Path(caminho).open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            apelido = (linha.get("apelido_real") or "").strip()
            if apelido:
                gabarito[linha["id_evento"]] = apelido
    return gabarito


def registros_do_indice(caminho: str | Path) -> list[metricas.Registro]:
    """O índice de miniaturas (agente.identidade.ARQUIVO_INDICE) como registros.

    Serve para medir a execução ao vivo exatamente como ela aconteceu, sem
    trilha e sem replay.
    """
    from datetime import datetime

    registros = []
    with Path(caminho).open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            registros.append(metricas.Registro(
                linha["id_evento"],
                datetime.fromisoformat(linha["instante"]),
                Direcao(linha["direcao"]),
                linha["pseudonimo"] or None,
            ))
    return registros


# A grade da varredura. Como em reprocessar.py: pequena de propósito.
GRADE = {
    "limiar_saida": [0.5, 0.6, 0.7, 0.8, 0.9],
    "limiar_reentrada": [0.6, 0.7, 0.8, 0.9],
    "janela_lote_s": [0.0, 60.0],
}


def varrer(
    trilha: Trilha,
    montar_linha: Callable[[], object],
    galeria_base: Galeria,
    gabarito: dict[str, str] | None = None,
    grade: dict[str, list] | None = None,
) -> list[dict]:
    """Uma linha de resumo por combinação da grade."""
    grade = grade or GRADE
    linhas = []
    for saida in grade["limiar_saida"]:
        for reentrada in grade["limiar_reentrada"]:
            for janela in grade["janela_lote_s"]:
                galeria = Galeria(
                    limiar_saida=saida,
                    limiar_reentrada=reentrada,
                    janela_lote_s=janela,
                    max_permanencia_h=galeria_base.max_permanencia_h,
                    memoria=galeria_base.memoria,
                )
                _, decisoes = recontar(trilha, montar_linha(), galeria)
                r = metricas.resumo(registros_de(decisoes), gabarito)
                r.update({
                    "limiar_saida": saida,
                    "limiar_reentrada": reentrada,
                    "janela_lote_s": janela,
                    "reentradas": galeria.reentradas,
                })
                linhas.append(r)
    return linhas
