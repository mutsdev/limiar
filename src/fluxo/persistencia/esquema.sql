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

-- Período de teste nomeado ("Teste de campo 03/09", "Laboratório de física").
-- É um rótulo sobre um intervalo de tempo, não uma coluna no evento: o evento
-- continua sendo só porta, instante e direção, e o período é lido por cima
-- na consulta. `fim` NULL é período em andamento. `camera_id` NULL é todas.
CREATE TABLE IF NOT EXISTS periodo (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL UNIQUE,
    camera_id  TEXT REFERENCES camera(id),
    inicio     TEXT NOT NULL,   -- ISO-8601 com fuso
    fim        TEXT,            -- ISO-8601 com fuso; NULL = aberto
    observacao TEXT,
    criado_em  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Etapa 2: re-identificação anônima.
--
-- O cabeçalho deste arquivo continua valendo. `pseudonimo` é "P7": um rótulo
-- do dia, que nasce da roupa e morre com ela. Expira por construção — a coluna
-- `expira_em` é lida por repositorio.purgar_expirados a cada escrita — e não
-- há caminho dele para nome, matrícula ou rosto. Nenhuma coluna aqui guarda
-- imagem nem vetor de aparência: o vetor vive na memória do agente e, quando
-- muito, numa trilha em dados/, fora do banco e fora do git.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pessoa_sessao (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id      TEXT NOT NULL REFERENCES camera(id),
    data_ref       TEXT NOT NULL,
    pseudonimo     TEXT NOT NULL,
    primeiro_visto TEXT NOT NULL,
    ultimo_visto   TEXT NOT NULL,
    expira_em      TEXT NOT NULL,
    UNIQUE (camera_id, data_ref, pseudonimo)
);

-- Liga um evento a um pseudônimo — ou a nenhum. `pessoa_id` NULL é a saída
-- que ficou sem par, e é dado de primeira classe: a fração de "não sei" é o
-- que torna o resultado honesto.
--
-- Sem FOREIGN KEY para evento.id_evento de propósito: os eventos saem do
-- agente em lotes de 25, e o vínculo pode chegar antes do evento. A junção é
-- feita na consulta.
CREATE TABLE IF NOT EXISTS vinculo (
    id_evento    TEXT PRIMARY KEY,
    camera_id    TEXT NOT NULL REFERENCES camera(id),
    data_ref     TEXT NOT NULL,
    pessoa_id    INTEGER REFERENCES pessoa_sessao(id),
    similaridade REAL,
    atribuido    INTEGER NOT NULL,
    metodo       TEXT NOT NULL
                 CHECK (metodo IN ('nova','reentrada','saida','nao_atribuido')),
    recebido_em  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vinculo_data ON vinculo(data_ref, camera_id);

-- Só para o teste de validação com pessoas conhecidas: é a ÚNICA tabela que
-- pode ligar um pseudônimo a alguém, e por isso está separada. Em operação
-- fica vazia, e o painel nem a exibe.
CREATE TABLE IF NOT EXISTS apelido_teste (
    pessoa_id  INTEGER PRIMARY KEY REFERENCES pessoa_sessao(id),
    apelido    TEXT NOT NULL,
    anotado_em TEXT NOT NULL
);
