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
    FimExecucao,
    InicioExecucao,
    Origem,
    RespostaEvento,
    RespostaExecucao,
    RespostaLote,
)
from fluxo.dominio.identidade import Apelido, PessoaSessao, RespostaVinculos, Vinculo
from fluxo.persistencia import repositorio
from fluxo.persistencia.repositorio import CameraDesconhecida, PessoaDesconhecida
from fluxo.servico.dependencias import obter_conexao
from fluxo.servico.seguranca import exigir_chave

# Só as rotas de escrita exigem chave (quando CHAVE_API está definida): as de
# consulta servem agregados sem identidade e o painel lê o banco direto.
COM_CHAVE = [Depends(exigir_chave)]

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
        # Pseudônimo vencido não sobrevive a um reinício do serviço.
        repositorio.purgar_expirados(conn)
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


@app.post("/eventos", response_model=RespostaEvento, tags=["ingestão"], dependencies=COM_CHAVE)
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


@app.post(
    "/eventos/lote", response_model=RespostaLote, tags=["ingestão"], dependencies=COM_CHAVE
)
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


@app.post(
    "/execucoes", response_model=RespostaExecucao, tags=["operação"], dependencies=COM_CHAVE
)
def abrir_execucao(
    inicio: InicioExecucao,
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> RespostaExecucao:
    """Registra o começo de uma execução do agente."""
    if not repositorio.camera_existe(conn, inicio.camera_id):
        raise HTTPException(
            status_code=404, detail=f"Câmera '{inicio.camera_id}' não está cadastrada."
        )
    execucao_id = repositorio.registrar_execucao(
        conn,
        inicio.camera_id,
        inicio.fonte,
        inicio.modelo,
        inicio.rastreador,
        inicio.conf_minima,
        inicio.versao_codigo,
    )
    return RespostaExecucao(execucao_id=execucao_id)


@app.post("/execucoes/{execucao_id}/fim", tags=["operação"], dependencies=COM_CHAVE)
def fechar_execucao(
    execucao_id: int,
    fim: FimExecucao,
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> dict[str, bool]:
    existe = conn.execute(
        "SELECT 1 FROM execucao WHERE id = ?", (execucao_id,)
    ).fetchone()
    if existe is None:
        raise HTTPException(status_code=404, detail=f"Execução {execucao_id} não existe.")
    repositorio.finalizar_execucao(conn, execucao_id, fim.quadros, fim.eventos)
    return {"fechada": True}


@app.get("/execucoes", tags=["consulta"])
def listar_execucoes(
    camera_id: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=500),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    sql = "SELECT * FROM execucao"
    params: list[object] = []
    if camera_id:
        sql += " WHERE camera_id = ?"
        params.append(camera_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limite)
    return [dict(linha) for linha in conn.execute(sql, params)]


# --------------------------------------------------------------------------
# Etapa 2 — identidade anônima
# --------------------------------------------------------------------------


@app.post("/pessoas/lote", tags=["identidade"], dependencies=COM_CHAVE)
def registrar_pessoas(
    pessoas: list[PessoaSessao],
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> dict[str, int]:
    """Pseudônimos do dia. Reenvio só alarga primeiro/último visto."""
    try:
        gravados = repositorio.upsert_pessoas(conn, pessoas)
    except CameraDesconhecida as erro:
        raise HTTPException(
            status_code=404, detail=f"Câmera '{erro.args[0]}' não está cadastrada."
        ) from erro
    return {"recebidos": len(pessoas), "gravados": gravados}


@app.post(
    "/vinculos/lote", response_model=RespostaVinculos, tags=["identidade"], dependencies=COM_CHAVE
)
def registrar_vinculos(
    vinculos: list[Vinculo],
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> RespostaVinculos:
    """Evento -> pseudônimo (ou nenhum). A chave é o id do evento: reenvio substitui."""
    try:
        gravados = repositorio.upsert_vinculos(conn, vinculos)
    except CameraDesconhecida as erro:
        raise HTTPException(
            status_code=404, detail=f"Câmera '{erro.args[0]}' não está cadastrada."
        ) from erro
    return RespostaVinculos(recebidos=len(vinculos), gravados=gravados)


@app.put("/pessoas/apelido", tags=["identidade"], dependencies=COM_CHAVE)
def definir_apelido(
    apelido: Apelido,
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> dict[str, bool]:
    """Só para o teste de validação: dá nome a um pseudônimo. Em operação, não se usa."""
    try:
        repositorio.definir_apelido(conn, apelido)
    except PessoaDesconhecida as erro:
        raise HTTPException(
            status_code=404, detail=f"Pseudônimo {erro.args[0]} não existe."
        ) from erro
    return {"definido": True}


@app.get("/pessoas", tags=["consulta"])
def listar_pessoas(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    linhas = repositorio.listar_pessoas(conn, data_inicio, data_fim, camera_id)
    return [dict(linha) for linha in linhas]


@app.get("/vinculos", tags=["consulta"])
def listar_vinculos(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(obter_conexao),
) -> list[dict]:
    linhas = repositorio.listar_vinculos(conn, data_inicio, data_fim, camera_id)
    return [dict(linha) for linha in linhas]
