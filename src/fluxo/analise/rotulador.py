"""Rotulador web: dizer quais travessias são a mesma pessoa, no navegador.

    python scripts/rotular_pessoas.py --web

Em vez de abrir a pasta de recortes e o CSV lado a lado: as miniaturas do dia
aparecem em grade, você marca as que são a mesma pessoa e dá um nome. Grava em
dados/gabaritos/<data>_<camera>.csv — a mesma coluna `apelido_real` que
`--metricas` lê, então nada mais na medição muda.

Imagem de pessoa real, mesmo regime das miniaturas (PROJETO §16.2): só neste
passo, disco local, apague a pasta quando o gabarito estiver pronto.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

if __package__ in (None, ""):  # rodado direto pelo streamlit
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from fluxo import config
from fluxo.agente.identidade import ARQUIVO_INDICE
from fluxo.avaliacao.identidade import COLUNAS_GABARITO

st.set_page_config(page_title="Rotular pessoas", page_icon="🏷️", layout="wide")

POR_LINHA = 6
SEM_NOME = "(sem nome)"


def dias_gravados() -> list[tuple[str, str]]:
    """(data, câmera) de cada pasta de recortes com índice, mais nova primeiro."""
    raiz = config.CAMINHO_RECORTES
    if not raiz.exists():
        return []
    achados = [
        (indice.parent.parent.name, indice.parent.name)
        for indice in raiz.glob(f"*/*/{ARQUIVO_INDICE}")
    ]
    return sorted(achados, reverse=True)


def caminho_gabarito(data: str, camera: str) -> Path:
    return config.CAMINHO_GABARITOS / f"{data}_{camera}.csv"


def carregar(data: str, camera: str) -> list[dict]:
    """As travessias do dia, com o apelido_real que já estiver gravado.

    Lê do índice e só aproveita a coluna do gabarito: o índice é a verdade de
    quais travessias existem, e assim o `--gerar` deixa de ser obrigatório.
    """
    pasta = config.CAMINHO_RECORTES / data / camera
    with (pasta / ARQUIVO_INDICE).open(encoding="utf-8", newline="") as f:
        linhas = [dict(linha) for linha in csv.DictReader(f)]

    destino = caminho_gabarito(data, camera)
    feito: dict[str, str] = {}
    if destino.exists():
        with destino.open(encoding="utf-8", newline="") as f:
            feito = {
                linha["id_evento"]: (linha.get("apelido_real") or "").strip()
                for linha in csv.DictReader(f)
            }
    for linha in linhas:
        linha["apelido_real"] = feito.get(linha["id_evento"], "")
    return linhas


def gravar(data: str, camera: str, linhas: list[dict]) -> Path:
    destino = caminho_gabarito(data, camera)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_GABARITO, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(linhas)
    return destino


def por_nome(linhas: list[dict]) -> dict[str, list[dict]]:
    """Grupos na ordem em que o nome apareceu; os sem nome primeiro."""
    grupos: dict[str, list[dict]] = {SEM_NOME: []}
    for linha in linhas:
        grupos.setdefault(linha["apelido_real"] or SEM_NOME, []).append(linha)
    return grupos


def _chave(linha: dict) -> str:
    # A "geração" entra na chave porque o Streamlit proíbe mexer no estado de
    # um widget já desenhado: trocar a chave é o jeito de limpar as caixas.
    return f"sel{st.session_state.get('geracao', 0)}_{linha['id_evento']}"


def desmarcar() -> None:
    st.session_state["geracao"] = st.session_state.get("geracao", 0) + 1


def grade(linhas: list[dict], pasta: Path) -> None:
    """Miniaturas em grade, cada uma com a caixa de seleção."""
    for i in range(0, len(linhas), POR_LINHA):
        for coluna, linha in zip(st.columns(POR_LINHA), linhas[i : i + POR_LINHA], strict=False):
            with coluna:
                st.image(str(pasta / linha["arquivo"]), use_container_width=True)
                hora = linha["instante"][11:19]
                seta = "entra" if linha["direcao"] == "ENTRADA" else "sai"
                st.checkbox(
                    f"{hora} {seta} · {linha['pseudonimo'] or '?'}", key=_chave(linha)
                )


# ============================================================== a página
st.title("Rotular pessoas")

opcoes = dias_gravados()
if not opcoes:
    st.info(
        f"Nenhuma pasta de recortes em `{config.CAMINHO_RECORTES}`.\n\n"
        "Rode antes: `python scripts/identificar_pessoas.py <camera> --guardar-recortes`"
    )
    st.stop()

data, camera = st.sidebar.selectbox(
    "Dia", opcoes, format_func=lambda dc: f"{dc[0]} · {dc[1]}"
)
linhas = carregar(data, camera)
pasta = config.CAMINHO_RECORTES / data / camera
grupos = por_nome(linhas)
nomes = [n for n in grupos if n != SEM_NOME]
sem_nome = grupos.pop(SEM_NOME)

a, b, c = st.columns(3)
a.metric("Travessias", len(linhas))
b.metric("Rotuladas", len(linhas) - len(sem_nome))
c.metric("Pessoas", len(nomes))

if sem_nome:
    st.subheader(f"Sem nome ({len(sem_nome)})")
    grade(sem_nome, pasta)

for nome, do_grupo in grupos.items():
    st.subheader(f"{nome} ({len(do_grupo)})")
    grade(do_grupo, pasta)

# --------------------------------------------------------- barra de ações
# Na barra lateral porque ela é desenhada depois da grade no código, e assim
# já lê as caixas marcadas nesta mesma passada — sem estado paralelo.
escolhidas = [linha for linha in linhas if st.session_state.get(_chave(linha))]
st.sidebar.divider()
st.sidebar.write(f"**{len(escolhidas)} marcada(s)**")

nome_novo = st.sidebar.text_input("Nome", placeholder=f"pessoa{len(nomes) + 1}")
alvo = st.sidebar.selectbox("ou juntar em", ["—", *nomes])

if st.sidebar.button("São a mesma pessoa", type="primary", disabled=not escolhidas):
    nome = nome_novo.strip() or (alvo if alvo != "—" else f"pessoa{len(nomes) + 1}")
    for linha in escolhidas:
        linha["apelido_real"] = nome
    gravar(data, camera, linhas)
    desmarcar()
    st.rerun()

if st.sidebar.button("Não sei (tirar o nome)", disabled=not escolhidas):
    for linha in escolhidas:
        linha["apelido_real"] = ""
    gravar(data, camera, linhas)
    desmarcar()
    st.rerun()

if st.sidebar.button("Desmarcar tudo", disabled=not escolhidas):
    desmarcar()
    st.rerun()

st.sidebar.divider()
st.sidebar.caption(f"Grava em `{caminho_gabarito(data, camera)}`. Depois:")
st.sidebar.code(f'python scripts/rotular_pessoas.py --metricas "{caminho_gabarito(data, camera)}"')
st.sidebar.caption(
    "As miniaturas são imagem de pessoa real (PROJETO §16.2). "
    "Apague `dados/recortes/` quando o gabarito estiver pronto."
)
