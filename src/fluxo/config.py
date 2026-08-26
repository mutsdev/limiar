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

# O banco mora fora do OneDrive: sincronização concorrente corrompe SQLite.
CAMINHO_BANCO = _caminho(
    "CAMINHO_BANCO",
    Path.home() / "Documents" / "dados-fluxo" / "fluxo.db",
)

# Configuração declarativa, versionada.
CAMINHO_CONFIG = RAIZ / "config"
ARQUIVO_CAMERAS = CAMINHO_CONFIG / "cameras.yaml"
ARQUIVO_PIPELINE = CAMINHO_CONFIG / "pipeline.yaml"

URL_SERVICO = os.getenv("URL_SERVICO", "http://127.0.0.1:8000").rstrip("/")

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
        CAMINHO_BANCO.parent,
    ):
        pasta.mkdir(parents=True, exist_ok=True)
