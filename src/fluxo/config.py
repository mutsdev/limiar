"""Configuração central do projeto.

Todo caminho do sistema sai daqui, e sai absoluto. Nenhum módulo monta caminho
relativo nem chama os.chdir(): caminho relativo depende de onde o processo foi
iniciado, e o bug resultante só aparece quando alguém roda o script de outra
pasta — tarde, e difícil de rastrear.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .../src/fluxo/config.py -> .../  (raiz do repositório)
RAIZ = Path(__file__).resolve().parents[2]

load_dotenv(RAIZ / ".env")


def _caminho(variavel: str, padrao: Path) -> Path:
    """Lê um caminho do ambiente, sempre devolvendo absoluto."""
    bruto = os.getenv(variavel, "").strip()
    return Path(bruto).expanduser().resolve() if bruto else padrao


# Vídeos, gravações e contagens manuais. Dado de pessoa real: fora do git.
CAMINHO_DADOS = _caminho("CAMINHO_DADOS", RAIZ / "dados")

CAMINHO_VIDEOS = CAMINHO_DADOS / "videos"
CAMINHO_GROUND_TRUTH = CAMINHO_DADOS / "ground_truth"
CAMINHO_SAIDAS = CAMINHO_DADOS / "saidas"

# Etapa 2. Trilhas e miniaturas de pessoas são dado de pessoa real: em dados/,
# fora do git, e apagáveis. O gabarito é o que o João Pedro preenche à mão.
CAMINHO_TRILHAS = CAMINHO_DADOS / "trilhas"
CAMINHO_RECORTES = CAMINHO_DADOS / "recortes"
CAMINHO_GABARITOS = CAMINHO_DADOS / "gabaritos"

# O banco mora fora do OneDrive: sincronização concorrente corrompe SQLite.
CAMINHO_BANCO = _caminho(
    "CAMINHO_BANCO",
    Path.home() / "Documents" / "dados-fluxo" / "fluxo.db",
)

# Logs e backups moram junto do banco pela mesma razão: escrita contínua e
# sincronização de nuvem não convivem.
CAMINHO_LOGS = _caminho("CAMINHO_LOGS", CAMINHO_BANCO.parent / "logs")
CAMINHO_BACKUPS = _caminho("CAMINHO_BACKUPS", CAMINHO_BANCO.parent / "backups")

# Pesos baixados (torchvision, re-ID). Ao lado do banco pelo tamanho: centenas
# de megabytes não têm o que fazer numa pasta sincronizada.
CAMINHO_MODELOS = _caminho("CAMINHO_MODELOS", CAMINHO_BANCO.parent / "modelos")

# Último quadro anotado de cada câmera, para a aba "Ao vivo" do painel. Um
# arquivo por câmera, sobrescrito o tempo todo — não é gravação. Junto do
# banco porque é escrita contínua.
CAMINHO_QUADROS = _caminho("CAMINHO_QUADROS", CAMINHO_BANCO.parent / "quadros")

# Binários baixados sem admin (o cloudflared do túnel). Junto do banco porque é
# da máquina, não do repositório.
CAMINHO_FERRAMENTAS = _caminho("CAMINHO_FERRAMENTAS", CAMINHO_BANCO.parent / "ferramentas")

# Configuração declarativa, versionada.
CAMINHO_CONFIG = RAIZ / "config"
ARQUIVO_CAMERAS = CAMINHO_CONFIG / "cameras.yaml"
ARQUIVO_PIPELINE = CAMINHO_CONFIG / "pipeline.yaml"

URL_SERVICO = os.getenv("URL_SERVICO", "http://127.0.0.1:8000").rstrip("/")

# Chave exigida nas rotas de escrita do serviço quando definida. Vazia deixa
# tudo aberto — o certo para localhost. Antes de expor com --host 0.0.0.0,
# defina a mesma chave no .env dos dois lados (docs/operacao.md).
CHAVE_API = os.getenv("CHAVE_API", "").strip()

# Senha do painel. Vazia = sem porta, o certo para localhost. Obrigatória antes
# de expor o painel por túnel: a aba "Ao vivo" mostra a porta da faculdade.
SENHA_PAINEL = os.getenv("SENHA_PAINEL", "").strip()

# Para onde o supervisor manda a URL do túnel quando ela muda (um tópico do
# ntfy.sh, por exemplo). Vazia = não avisa ninguém; a URL fica só no log.
URL_AVISO = os.getenv("URL_AVISO", "").strip()

# Caminho do cloudflared, se não estiver no PATH nem em CAMINHO_FERRAMENTAS.
CLOUDFLARED = os.getenv("CLOUDFLARED", "").strip()

# Fuso fixo. `zoneinfo` no Windows depende do pacote tzdata, que nem sempre
# está presente; o projeto roda num único fuso e não precisa de mais que isso.
UTC_OFFSET_HORAS = -3


def carregar_cameras() -> dict[str, dict]:
    import yaml

    dados = yaml.safe_load(ARQUIVO_CAMERAS.read_text(encoding="utf-8")) or {}
    return dados.get("cameras") or {}


def carregar_pipeline() -> dict:
    import yaml

    return yaml.safe_load(ARQUIVO_PIPELINE.read_text(encoding="utf-8")) or {}


def salvar_cameras(cameras: dict[str, dict]) -> None:
    """Regrava cameras.yaml. Usado pela ferramenta de calibração."""
    import yaml

    cabecalho = (
        "# Uma entrada por câmera. A linha de contagem é escrita aqui por\n"
        "# scripts/calibrar_linha.py — não edite as coordenadas à mão.\n"
        "#\n"
        "# linha: [x1, y1, x2, y2] em pixels do quadro original\n"
        "# lado_dentro: sinal do produto vetorial correspondente ao interior\n"
        "#              do prédio; depende de como a câmera está montada.\n\n"
    )
    corpo = yaml.safe_dump(
        {"cameras": cameras}, allow_unicode=True, sort_keys=False, default_flow_style=None
    )
    ARQUIVO_CAMERAS.write_text(cabecalho + corpo, encoding="utf-8")


def garantir_pastas() -> None:
    """Cria as pastas de trabalho. Chamado pelos entrypoints, não na importação."""
    for pasta in (
        CAMINHO_DADOS,
        CAMINHO_VIDEOS,
        CAMINHO_GROUND_TRUTH,
        CAMINHO_SAIDAS,
        CAMINHO_TRILHAS,
        CAMINHO_RECORTES,
        CAMINHO_GABARITOS,
        CAMINHO_BANCO.parent,
        CAMINHO_LOGS,
        CAMINHO_BACKUPS,
        CAMINHO_MODELOS,
        CAMINHO_QUADROS,
        CAMINHO_FERRAMENTAS,
    ):
        pasta.mkdir(parents=True, exist_ok=True)
