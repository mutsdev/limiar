"""O serviço central: recebe os eventos das câmeras e responde consultas.

Ele existe separado do agente porque no local eles estarão em máquinas
diferentes — a câmera na porta, o banco no servidor. Nascer monolítico
significaria reescrever na hora de instalar.
"""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query

from fluxo.dominio.evento import (
    EventoCruzamento,
    Origem,
    RespostaEvento,
    RespostaLote,
)
from fluxo.persistencia import repositorio
from fluxo.persistencia.repositorio import CameraDesconhecida
from fluxo.servico.dependencias import obter_conexao

DESCRICAO = """
Recebe os eventos de cruzamento das câmeras das entradas e responde as
consultas agregadas.

O sistema registra **porta, instante e direção**. Não há imagem, não há rosto e
não há vínculo com identidade civil em nenhum ponto.
"""


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    conn = repositorio.conectar()
    try:
        repositorio.criar_banco(conn)
        for id_, nome, local, ativa in repositorio.cameras_do_yaml():
            repositorio.inserir_camera(conn, id_, nome, local, ativa)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="Limiar",
    description=DESCRICAO,
    version="0.1.0",
    lifespan=_ciclo_de_vida,
)


@app.get("/saude", tags=["operação"])
def saude() -> dict[str, str]:
    """Usado pelo agente para saber se vale a pena enviar ou enfileirar."""
    return {"status": "ok"}


@app.post("/eventos", response_model=RespostaEvento, tags=["ingestão"])
def registrar_evento(
    evento: EventoCruzamento,
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> RespostaEvento:
    """Registra um cruzamento.

    Reenvio do mesmo evento devolve 200 com `registrado: false`. Isso não é
    erro — é a deduplicação funcionando.
    """
    try:
        inserido = repositorio.inserir_evento(conn, evento)
    except CameraDesconhecida as erro:
        raise HTTPException(
            status_code=404,
            detail=f"Câmera '{erro.args[0]}' não está cadastrada. "
            f"Adicione-a em config/cameras.yaml e reinicie o serviço.",
        ) from erro

    return RespostaEvento(
        registrado=inserido,
        id_evento=evento.id_evento,
        detalhe="" if inserido else "Evento já registrado antes.",
    )


@app.post("/eventos/lote", response_model=RespostaLote, tags=["ingestão"])
def registrar_lote(
    eventos: list[EventoCruzamento],
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> RespostaLote:
    """Recebe a fila acumulada pelo agente enquanto a rede esteve fora."""
    try:
        registrados, duplicados = repositorio.inserir_eventos(conn, eventos)
    except CameraDesconhecida as erro:
        raise HTTPException(
            status_code=404, detail=f"Câmera '{erro.args[0]}' não está cadastrada."
        ) from erro

    return RespostaLote(
        recebidos=len(eventos), registrados=registrados, duplicados=duplicados
    )


@app.get("/cameras", tags=["consulta"])
def listar_cameras(conn: sqlite3.Connection = Depends(obter_conexao)) -> list[dict]:
    return [dict(linha) for linha in repositorio.listar_cameras(conn)]


@app.get("/contagem/diaria", tags=["consulta"])
def contagem_diaria(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    origem: Origem | None = Query(
        default=Origem.VISAO,
        description="Default VISAO. Passe SINTETICO para ver dados de simulação.",
    ),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    linhas = repositorio.contagem_diaria(conn, data_inicio, data_fim, camera_id, origem)
    return [dict(linha) for linha in linhas]


@app.get("/contagem/horaria", tags=["consulta"])
def contagem_horaria(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    origem: Origem | None = Query(default=Origem.VISAO),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    linhas = repositorio.contagem_horaria(conn, data_inicio, data_fim, camera_id, origem)
    return [dict(linha) for linha in linhas]


@app.get("/eventos", tags=["consulta"])
def listar_eventos(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    origem: Origem | None = Query(default=Origem.VISAO),
    limite: int = Query(default=200, ge=1, le=5000),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    linhas = repositorio.consultar_eventos(
        conn, data_inicio, data_fim, camera_id, origem, limite
    )
    return [dict(linha) for linha in linhas]
