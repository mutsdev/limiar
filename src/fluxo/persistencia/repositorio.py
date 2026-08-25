"""Acesso ao banco.

Quem escreve no banco é só o serviço central — um processo. Os agentes falam
HTTP. Isso evita contenção de escrita do SQLite entre as duas câmeras.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

from fluxo import config
from fluxo.dominio.evento import FUSO_LOCAL, EventoCruzamento, Origem

_ESQUEMA = Path(__file__).with_name("esquema.sql")


class CameraDesconhecida(Exception):
    """Evento chegou para uma câmera que não está cadastrada."""


def conectar(caminho: str | Path | None = None) -> sqlite3.Connection:
    """Abre conexão com os pragmas que o projeto exige."""
    alvo = config.CAMINHO_BANCO if caminho is None else caminho
    if alvo != ":memory:":
        alvo = Path(alvo)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo = str(alvo)

    conn = sqlite3.connect(alvo, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # WAL permite leitura (o painel) concorrente com escrita (o serviço).
    conn.execute("PRAGMA journal_mode=WAL")
    # Sem isto o SQLite aceita camera_id inexistente sem reclamar.
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def criar_banco(conn: sqlite3.Connection) -> None:
    conn.executescript(_ESQUEMA.read_text(encoding="utf-8"))
    conn.commit()


# --------------------------------------------------------------------------
# Câmeras
# --------------------------------------------------------------------------


def inserir_camera(
    conn: sqlite3.Connection, id_: str, nome: str, local: str = "", ativa: bool = True
) -> None:
    conn.execute(
        "INSERT INTO camera (id, nome, local, ativa) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, local=excluded.local, "
        "ativa=excluded.ativa",
        (id_, nome, local, int(ativa)),
    )
    conn.commit()


def listar_cameras(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM camera ORDER BY id"))


def camera_existe(conn: sqlite3.Connection, id_: str) -> bool:
    return conn.execute("SELECT 1 FROM camera WHERE id = ?", (id_,)).fetchone() is not None


# --------------------------------------------------------------------------
# Eventos
# --------------------------------------------------------------------------


def inserir_evento(conn: sqlite3.Connection, evento: EventoCruzamento) -> bool:
    """Grava o evento. Devolve False se ele já estava lá.

    O False não é erro: é o reenvio depois de uma falha de rede sendo
    reconhecido e descartado.
    """
    if not camera_existe(conn, evento.camera_id):
        raise CameraDesconhecida(evento.camera_id)

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO evento
            (id_evento, camera_id, instante, data_ref, direcao,
             track_id_local, confianca, origem, recebido_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evento.id_evento,
            evento.camera_id,
            evento.instante.isoformat(),
            evento.data_ref.isoformat(),
            evento.direcao.value,
            evento.track_id_local,
            evento.confianca,
            evento.origem.value,
            datetime.now(FUSO_LOCAL).isoformat(),
        ),
    )
    conn.commit()
    return cur.rowcount == 1


def inserir_eventos(
    conn: sqlite3.Connection, eventos: Iterable[EventoCruzamento]
) -> tuple[int, int]:
    """Insere um lote. Devolve (registrados, duplicados)."""
    registrados = duplicados = 0
    for evento in eventos:
        if inserir_evento(conn, evento):
            registrados += 1
        else:
            duplicados += 1
    return registrados, duplicados


def _filtros(
    data_inicio: date | None,
    data_fim: date | None,
    camera_id: str | None,
    origem: Origem | None,
) -> tuple[str, list[object]]:
    onde: list[str] = []
    params: list[object] = []
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
    return (" WHERE " + " AND ".join(onde) if onde else ""), params


def consultar_eventos(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
    origem: Origem | None = Origem.VISAO,
    limite: int | None = None,
) -> list[sqlite3.Row]:
    """Eventos brutos.

    `origem` tem default VISAO de propósito: quem quiser ver dado sintético
    precisa pedir. Assim ele não entra por engano num número de relatório.
    """
    onde, params = _filtros(data_inicio, data_fim, camera_id, origem)
    sql = f"SELECT * FROM evento{onde} ORDER BY instante"
    if limite is not None:
        sql += " LIMIT ?"
        params.append(limite)
    return list(conn.execute(sql, params))


def contagem_diaria(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
    origem: Origem | None = Origem.VISAO,
) -> list[sqlite3.Row]:
    onde, params = _filtros(data_inicio, data_fim, camera_id, origem)
    return list(
        conn.execute(
            f"""
            SELECT data_ref, camera_id, direcao, COUNT(*) AS total
            FROM evento{onde}
            GROUP BY data_ref, camera_id, direcao
            ORDER BY data_ref, camera_id, direcao
            """,
            params,
        )
    )


def contagem_horaria(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
    origem: Origem | None = Origem.VISAO,
) -> list[sqlite3.Row]:
    onde, params = _filtros(data_inicio, data_fim, camera_id, origem)
    # A hora sai do próprio texto ISO: posições 12-13 de "AAAA-MM-DDTHH:MM:SS".
    return list(
        conn.execute(
            f"""
            SELECT data_ref,
                   camera_id,
                   CAST(substr(instante, 12, 2) AS INTEGER) AS hora,
                   direcao,
                   COUNT(*) AS total
            FROM evento{onde}
            GROUP BY data_ref, camera_id, hora, direcao
            ORDER BY data_ref, camera_id, hora, direcao
            """,
            params,
        )
    )


# --------------------------------------------------------------------------
# Execuções
# --------------------------------------------------------------------------


def registrar_execucao(
    conn: sqlite3.Connection,
    camera_id: str,
    fonte: str,
    modelo: str,
    rastreador: str,
    conf_minima: float,
    versao_codigo: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO execucao
            (camera_id, fonte, modelo, rastreador, conf_minima, inicio, versao_codigo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            camera_id,
            fonte,
            modelo,
            rastreador,
            conf_minima,
            datetime.now(FUSO_LOCAL).isoformat(),
            versao_codigo,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def finalizar_execucao(
    conn: sqlite3.Connection, execucao_id: int, quadros: int, eventos: int
) -> None:
    conn.execute(
        "UPDATE execucao SET fim = ?, quadros = ?, eventos = ? WHERE id = ?",
        (datetime.now(FUSO_LOCAL).isoformat(), quadros, eventos, execucao_id),
    )
    conn.commit()


def cameras_do_yaml() -> Sequence[tuple[str, str, str, bool]]:
    """Lê config/cameras.yaml e devolve as tuplas de cadastro."""
    import yaml

    dados = yaml.safe_load(config.ARQUIVO_CAMERAS.read_text(encoding="utf-8")) or {}
    return [
        (id_, c.get("nome", id_), c.get("local", "") or "", bool(c.get("ativa", True)))
        for id_, c in (dados.get("cameras") or {}).items()
    ]
