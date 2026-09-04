"""Acesso ao banco.

Quem escreve no banco é só o serviço central — um processo. Os agentes falam
HTTP. Isso evita contenção de escrita do SQLite entre as duas câmeras.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from fluxo import config
from fluxo.dominio.evento import FUSO_LOCAL, HORA_INICIO_DIA, EventoCruzamento, Origem
from fluxo.dominio.identidade import Apelido, PessoaSessao, Vinculo
from fluxo.dominio.periodo import Periodo

_ESQUEMA = Path(__file__).with_name("esquema.sql")

# PROJETO §16.5: o pseudônimo expira em 24-48 h. Quem chama pode apertar.
EXPIRA_H = 48.0


class CameraDesconhecida(Exception):
    """Evento chegou para uma câmera que não está cadastrada."""


class PessoaDesconhecida(Exception):
    """Apelido para um pseudônimo que não existe naquele dia e câmera."""


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


# --------------------------------------------------------------------------
# Etapa 2 — pessoas de sessão, vínculos e apelidos de teste
# --------------------------------------------------------------------------


def _expira_em(data_ref: date, expira_h: float) -> str:
    inicio = datetime(
        data_ref.year, data_ref.month, data_ref.day, HORA_INICIO_DIA, tzinfo=FUSO_LOCAL
    )
    return (inicio + timedelta(hours=expira_h)).isoformat()


def _onde(
    prefixo: str,
    data_inicio: date | None,
    data_fim: date | None,
    camera_id: str | None,
) -> tuple[str, list[object]]:
    """Como _filtros, mas com o alias da tabela: as consultas daqui têm JOIN."""
    onde: list[str] = []
    params: list[object] = []
    if data_inicio is not None:
        onde.append(f"{prefixo}.data_ref >= ?")
        params.append(data_inicio.isoformat())
    if data_fim is not None:
        onde.append(f"{prefixo}.data_ref <= ?")
        params.append(data_fim.isoformat())
    if camera_id is not None:
        onde.append(f"{prefixo}.camera_id = ?")
        params.append(camera_id)
    return (" WHERE " + " AND ".join(onde) if onde else ""), params


def purgar_expirados(
    conn: sqlite3.Connection, agora: datetime | None = None, expira_h: float = EXPIRA_H
) -> int:
    """Apaga o que passou de `expira_em`. Devolve quantas pessoas sumiram.

    Chamado a cada escrita e no arranque do serviço: a expiração é mecânica,
    não um procedimento que alguém precisa lembrar de rodar.
    """
    agora = agora or datetime.now(FUSO_LOCAL)
    ids = [
        r[0] for r in conn.execute(
            "SELECT id FROM pessoa_sessao WHERE expira_em < ?", (agora.isoformat(),)
        )
    ]
    if ids:
        marcas = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM apelido_teste WHERE pessoa_id IN ({marcas})", ids)
        conn.execute(f"DELETE FROM vinculo WHERE pessoa_id IN ({marcas})", ids)
        conn.execute(f"DELETE FROM pessoa_sessao WHERE id IN ({marcas})", ids)
    # Vínculo sem pessoa (saída sem par) não aponta para ninguém, mas também
    # não tem por que sobreviver ao dia que descreve.
    corte = (agora - timedelta(hours=expira_h)).date().isoformat()
    conn.execute("DELETE FROM vinculo WHERE pessoa_id IS NULL AND data_ref < ?", (corte,))
    conn.commit()
    return len(ids)


def _pessoa_id(
    conn: sqlite3.Connection, camera_id: str, data_ref: date, pseudonimo: str
) -> int | None:
    linha = conn.execute(
        "SELECT id FROM pessoa_sessao WHERE camera_id = ? AND data_ref = ? AND pseudonimo = ?",
        (camera_id, data_ref.isoformat(), pseudonimo),
    ).fetchone()
    return None if linha is None else int(linha[0])


def upsert_pessoas(
    conn: sqlite3.Connection, pessoas: Iterable[PessoaSessao], expira_h: float = EXPIRA_H
) -> int:
    """Grava ou atualiza pessoas de sessão. Reenvio alarga as datas, não duplica."""
    n = 0
    for p in pessoas:
        if not camera_existe(conn, p.camera_id):
            raise CameraDesconhecida(p.camera_id)
        conn.execute(
            """
            INSERT INTO pessoa_sessao
                (camera_id, data_ref, pseudonimo, primeiro_visto, ultimo_visto, expira_em)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(camera_id, data_ref, pseudonimo) DO UPDATE SET
                primeiro_visto = MIN(pessoa_sessao.primeiro_visto, excluded.primeiro_visto),
                ultimo_visto   = MAX(pessoa_sessao.ultimo_visto, excluded.ultimo_visto)
            """,
            (
                p.camera_id,
                p.data_ref.isoformat(),
                p.pseudonimo,
                p.primeiro_visto.isoformat(),
                p.ultimo_visto.isoformat(),
                _expira_em(p.data_ref, expira_h),
            ),
        )
        n += 1
    conn.commit()
    purgar_expirados(conn, expira_h=expira_h)
    return n


def upsert_vinculos(
    conn: sqlite3.Connection, vinculos: Iterable[Vinculo], expira_h: float = EXPIRA_H
) -> int:
    """Grava ou substitui vínculos. A chave é o id do evento.

    Vínculo que chega antes da pessoa (o POST dela falhou, ou a ordem trocou
    na fila) cria a pessoa com o que se sabe; o upsert dela corrige as datas
    depois. Perder o vínculo seria pior que uma data provisória.
    """
    n = 0
    agora = datetime.now(FUSO_LOCAL).isoformat()
    for v in vinculos:
        if not camera_existe(conn, v.camera_id):
            raise CameraDesconhecida(v.camera_id)
        pessoa_id = None
        if v.pseudonimo is not None:
            pessoa_id = _pessoa_id(conn, v.camera_id, v.data_ref, v.pseudonimo)
            if pessoa_id is None:
                cur = conn.execute(
                    """
                    INSERT INTO pessoa_sessao
                        (camera_id, data_ref, pseudonimo, primeiro_visto, ultimo_visto, expira_em)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (v.camera_id, v.data_ref.isoformat(), v.pseudonimo, agora, agora,
                     _expira_em(v.data_ref, expira_h)),
                )
                pessoa_id = int(cur.lastrowid or 0)
        conn.execute(
            """
            INSERT INTO vinculo
                (id_evento, camera_id, data_ref, pessoa_id, similaridade,
                 atribuido, metodo, recebido_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id_evento) DO UPDATE SET
                pessoa_id = excluded.pessoa_id,
                similaridade = excluded.similaridade,
                atribuido = excluded.atribuido,
                metodo = excluded.metodo,
                recebido_em = excluded.recebido_em
            """,
            (
                v.id_evento, v.camera_id, v.data_ref.isoformat(), pessoa_id,
                v.similaridade, int(v.atribuido), v.metodo, agora,
            ),
        )
        n += 1
    conn.commit()
    # Também aqui: a pessoa provisória criada acima pode já ter nascido
    # vencida (replay de um vídeo antigo), e não deve esperar a próxima escrita.
    purgar_expirados(conn, expira_h=expira_h)
    return n


def definir_apelido(conn: sqlite3.Connection, apelido: Apelido) -> None:
    pessoa_id = _pessoa_id(conn, apelido.camera_id, apelido.data_ref, apelido.pseudonimo)
    if pessoa_id is None:
        raise PessoaDesconhecida(
            f"{apelido.pseudonimo} em {apelido.data_ref.isoformat()} ({apelido.camera_id})"
        )
    conn.execute(
        """
        INSERT INTO apelido_teste (pessoa_id, apelido, anotado_em) VALUES (?, ?, ?)
        ON CONFLICT(pessoa_id) DO UPDATE SET
            apelido = excluded.apelido, anotado_em = excluded.anotado_em
        """,
        (pessoa_id, apelido.apelido, datetime.now(FUSO_LOCAL).isoformat()),
    )
    conn.commit()


def listar_pessoas(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
) -> list[sqlite3.Row]:
    """Uma linha por pseudônimo, com apelido (se houver) e quantas travessias."""
    onde, params = _onde("p", data_inicio, data_fim, camera_id)
    return list(
        conn.execute(
            f"""
            SELECT p.id, p.camera_id, p.data_ref, p.pseudonimo,
                   p.primeiro_visto, p.ultimo_visto, a.apelido,
                   SUM(CASE WHEN e.direcao = 'ENTRADA' THEN 1 ELSE 0 END) AS entradas,
                   SUM(CASE WHEN e.direcao = 'SAIDA' THEN 1 ELSE 0 END) AS saidas
            FROM pessoa_sessao p
            LEFT JOIN apelido_teste a ON a.pessoa_id = p.id
            LEFT JOIN vinculo v ON v.pessoa_id = p.id
            LEFT JOIN evento e ON e.id_evento = v.id_evento
            {onde}
            GROUP BY p.id
            ORDER BY p.data_ref, p.camera_id, CAST(substr(p.pseudonimo, 2) AS INTEGER)
            """,
            params,
        )
    )


def listar_vinculos(
    conn: sqlite3.Connection,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    camera_id: str | None = None,
) -> list[sqlite3.Row]:
    """Vínculos com o instante e a direção do evento, para relatório e painel."""
    onde, params = _onde("v", data_inicio, data_fim, camera_id)
    return list(
        conn.execute(
            f"""
            SELECT v.id_evento, v.camera_id, v.data_ref, v.similaridade, v.atribuido,
                   v.metodo, p.pseudonimo, a.apelido, e.instante, e.direcao
            FROM vinculo v
            LEFT JOIN pessoa_sessao p ON p.id = v.pessoa_id
            LEFT JOIN apelido_teste a ON a.pessoa_id = p.id
            LEFT JOIN evento e ON e.id_evento = v.id_evento
            {onde}
            ORDER BY e.instante, v.id_evento
            """,
            params,
        )
    )


# --------------------------------------------------------------------------
# Períodos de teste
# --------------------------------------------------------------------------


class PeriodoDuplicado(Exception):
    """Já existe um período com esse nome."""


class PeriodoDesconhecido(Exception):
    """Nenhum período com esse id ou nome."""


def _periodo_de(linha: sqlite3.Row) -> Periodo:
    return Periodo(
        id=linha["id"],
        nome=linha["nome"],
        inicio=datetime.fromisoformat(linha["inicio"]),
        fim=datetime.fromisoformat(linha["fim"]) if linha["fim"] else None,
        camera_id=linha["camera_id"],
        observacao=linha["observacao"],
    )


def _com_fuso(instante: datetime) -> datetime:
    return instante.replace(tzinfo=FUSO_LOCAL) if instante.tzinfo is None else instante


def criar_periodo(
    conn: sqlite3.Connection,
    nome: str,
    inicio: datetime,
    fim: datetime | None = None,
    camera_id: str | None = None,
    observacao: str | None = None,
) -> Periodo:
    nome = nome.strip()
    if not nome:
        raise ValueError("Período precisa de nome.")
    if camera_id is not None and not camera_existe(conn, camera_id):
        raise CameraDesconhecida(camera_id)
    inicio = _com_fuso(inicio)
    fim = _com_fuso(fim) if fim is not None else None
    if fim is not None and fim < inicio:
        raise ValueError("Fim do período antes do início.")
    try:
        cur = conn.execute(
            "INSERT INTO periodo (nome, camera_id, inicio, fim, observacao, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                nome, camera_id, inicio.isoformat(),
                fim.isoformat() if fim else None, observacao,
                datetime.now(FUSO_LOCAL).isoformat(),
            ),
        )
    except sqlite3.IntegrityError as erro:
        raise PeriodoDuplicado(nome) from erro
    conn.commit()
    return Periodo(cur.lastrowid, nome, inicio, fim, camera_id, observacao)


def listar_periodos(conn: sqlite3.Connection) -> list[Periodo]:
    """Do mais recente para o mais antigo — o de hoje vem primeiro no painel."""
    return [
        _periodo_de(r)
        for r in conn.execute("SELECT * FROM periodo ORDER BY inicio DESC, id DESC")
    ]


def periodo_por_nome(conn: sqlite3.Connection, nome: str) -> Periodo | None:
    linha = conn.execute("SELECT * FROM periodo WHERE nome = ?", (nome.strip(),)).fetchone()
    return _periodo_de(linha) if linha else None


def periodo_aberto(conn: sqlite3.Connection) -> Periodo | None:
    """O período em andamento mais recente, se houver."""
    linha = conn.execute(
        "SELECT * FROM periodo WHERE fim IS NULL ORDER BY inicio DESC, id DESC LIMIT 1"
    ).fetchone()
    return _periodo_de(linha) if linha else None


def _id_do_periodo(conn: sqlite3.Connection, periodo: int | str) -> int:
    if isinstance(periodo, int):
        if conn.execute("SELECT 1 FROM periodo WHERE id = ?", (periodo,)).fetchone() is None:
            raise PeriodoDesconhecido(periodo)
        return periodo
    achado = periodo_por_nome(conn, periodo)
    if achado is None or achado.id is None:
        raise PeriodoDesconhecido(periodo)
    return achado.id


def encerrar_periodo(
    conn: sqlite3.Connection, periodo: int | str, fim: datetime | None = None
) -> Periodo:
    id_ = _id_do_periodo(conn, periodo)
    fim = _com_fuso(fim) if fim is not None else datetime.now(FUSO_LOCAL)
    conn.execute("UPDATE periodo SET fim = ? WHERE id = ?", (fim.isoformat(), id_))
    conn.commit()
    return _periodo_de(conn.execute("SELECT * FROM periodo WHERE id = ?", (id_,)).fetchone())


def renomear_periodo(conn: sqlite3.Connection, periodo: int | str, novo_nome: str) -> Periodo:
    id_ = _id_do_periodo(conn, periodo)
    novo_nome = novo_nome.strip()
    if not novo_nome:
        raise ValueError("Período precisa de nome.")
    try:
        conn.execute("UPDATE periodo SET nome = ? WHERE id = ?", (novo_nome, id_))
    except sqlite3.IntegrityError as erro:
        raise PeriodoDuplicado(novo_nome) from erro
    conn.commit()
    return _periodo_de(conn.execute("SELECT * FROM periodo WHERE id = ?", (id_,)).fetchone())
