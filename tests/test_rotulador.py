"""O rotulador web: marcar duas miniaturas grava o mesmo apelido no gabarito.

Sem este teste, um rotulador quebrado só aparece como erro dentro da página —
e o gabarito é a régua de toda a medição da Etapa 2.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from fluxo import config

CAMINHO_APP = str(
    Path(__file__).resolve().parents[1] / "src" / "fluxo" / "analise" / "rotulador.py"
)
LINHAS = [
    ("ev-1", "2026-09-22T09:00:11-03:00", "ENTRADA", "P1", "nova", "P1/a.jpg"),
    ("ev-2", "2026-09-22T09:00:21-03:00", "SAIDA", "P2", "saida", "P2/b.jpg"),
]


@pytest.fixture
def recortes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Um dia de miniaturas de verdade (JPEG mesmo: o st.image abre o arquivo)."""
    from PIL import Image

    monkeypatch.setattr(config, "CAMINHO_RECORTES", tmp_path / "recortes")
    monkeypatch.setattr(config, "CAMINHO_GABARITOS", tmp_path / "gabaritos")
    pasta = config.CAMINHO_RECORTES / "2026-09-22" / "elevada"
    for _, _, _, _, _, arquivo in LINHAS:
        caminho = pasta / arquivo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 16), "gray").save(caminho)
    with (pasta / "indice.csv").open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(
            ["id_evento", "instante", "direcao", "pseudonimo", "metodo", "arquivo"]
        )
        escritor.writerows(LINHAS)
    return pasta


def test_sem_recortes_orienta_em_vez_de_quebrar(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CAMINHO_RECORTES", tmp_path / "vazio")
    app = AppTest.from_file(CAMINHO_APP, default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    assert "identificar_pessoas.py" in app.info[0].value


def test_marcar_duas_grava_o_mesmo_apelido(recortes):
    app = AppTest.from_file(CAMINHO_APP, default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.checkbox) == 2

    app.checkbox[0].check().run()
    app.checkbox[1].check().run()
    app.button[0].click().run()  # "São a mesma pessoa"
    assert not app.exception, [e.value for e in app.exception]

    gabarito = config.CAMINHO_GABARITOS / "2026-09-22_elevada.csv"
    with gabarito.open(encoding="utf-8", newline="") as f:
        apelidos = {linha["id_evento"]: linha["apelido_real"] for linha in csv.DictReader(f)}
    assert apelidos == {"ev-1": "pessoa1", "ev-2": "pessoa1"}

    # Recarregou com o nome, e as caixas voltaram limpas.
    assert not any(c.value for c in app.checkbox)
    app.checkbox[0].check().run()
    app.button[1].click().run()  # "Não sei (tirar o nome)"
    assert not app.exception, [e.value for e in app.exception]
    with gabarito.open(encoding="utf-8", newline="") as f:
        apelidos = {linha["id_evento"]: linha["apelido_real"] for linha in csv.DictReader(f)}
    assert apelidos == {"ev-1": "", "ev-2": "pessoa1"}
