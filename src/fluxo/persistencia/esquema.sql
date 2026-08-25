-- Esquema do Limiar.
-- Nenhuma coluna identifica pessoa. Isso é a definição do sistema, não uma
-- lacuna a preencher depois.

CREATE TABLE IF NOT EXISTS camera (
    id     TEXT PRIMARY KEY,
    nome   TEXT NOT NULL,
    local  TEXT,
    ativa  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS evento (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Chave de idempotência: o mesmo cruzamento reenviado colide aqui.
    id_evento      TEXT    NOT NULL UNIQUE,

    camera_id      TEXT    NOT NULL REFERENCES camera(id),
    instante       TEXT    NOT NULL,   -- ISO-8601 com fuso
    data_ref       TEXT    NOT NULL,   -- YYYY-MM-DD, dia operacional
    direcao        TEXT    NOT NULL CHECK (direcao IN ('ENTRADA','SAIDA')),
    track_id_local INTEGER,
    confianca      REAL,
    origem         TEXT    NOT NULL DEFAULT 'VISAO'
                   CHECK (origem IN ('VISAO','SINTETICO','MANUAL')),
    recebido_em    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evento_data     ON evento(data_ref, camera_id);
CREATE INDEX IF NOT EXISTS idx_evento_instante ON evento(instante);
CREATE INDEX IF NOT EXISTS idx_evento_origem   ON evento(origem);

-- Rastreabilidade da medição: com qual modelo e quais limiares aquele número
-- foi produzido. Sem isto, um resultado de seis semanas atrás é irreprodutível.
CREATE TABLE IF NOT EXISTS execucao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id     TEXT NOT NULL REFERENCES camera(id),
    fonte         TEXT NOT NULL,
    modelo        TEXT NOT NULL,
    rastreador    TEXT NOT NULL,
    conf_minima   REAL NOT NULL,
    inicio        TEXT NOT NULL,
    fim           TEXT,
    quadros       INTEGER,
    eventos       INTEGER,
    versao_codigo TEXT
);
