"""Painel web.

    python scripts/rodar_painel.py

É aqui que o valor do sistema fica visível: a série que hoje não existe.

É também a única porta que sai para fora da máquina (rodar_tudo.py --tunel),
e por isso exige senha quando SENHA_PAINEL está definida: a aba "Ao vivo"
mostra a porta da faculdade.
"""

from __future__ import annotations

import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):  # rodado direto pelo streamlit
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from fluxo import config
from fluxo.analise import consultas
from fluxo.dominio.evento import FUSO_LOCAL, Origem
from fluxo.dominio.periodo import Periodo
from fluxo.persistencia import backup, repositorio
from fluxo.visao.quadro_vivo import idade_do_quadro

st.set_page_config(page_title="Limiar", page_icon="🚪", layout="wide")

# Quadro mais velho que isto na aba Ao vivo é sinal de agente parado.
QUADRO_VELHO_S = 15.0


# ================================================================== senha
def _exigir_senha() -> None:
    if not config.SENHA_PAINEL or st.session_state.get("autenticado"):
        return
    caixa = st.empty()
    with caixa.container():
        st.title("Limiar")
        senha = st.text_input("Senha", type="password")
        if senha and secrets.compare_digest(senha, config.SENHA_PAINEL):
            st.session_state["autenticado"] = True
        elif senha:
            st.error("Senha incorreta.")
    if not st.session_state.get("autenticado"):
        st.stop()
    caixa.empty()


_exigir_senha()


# ================================================================== dados
@st.cache_data(ttl=30)
def _carregar(inicio: date, fim: date, camera: str | None, origem: str) -> pd.DataFrame:
    conn = repositorio.conectar()
    try:
        return consultas.carregar_eventos(conn, inicio, fim, camera, Origem(origem))
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _carregar_identidade(
    inicio: date, fim: date, camera: str | None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = repositorio.conectar()
    try:
        return (
            consultas.carregar_pessoas(conn, inicio, fim, camera),
            consultas.carregar_vinculos(conn, inicio, fim, camera),
        )
    finally:
        conn.close()


@st.cache_data(ttl=60)
def _cameras() -> list[str]:
    conn = repositorio.conectar()
    try:
        return [c["id"] for c in repositorio.listar_cameras(conn)]
    finally:
        conn.close()


@st.cache_data(ttl=30)
def _periodos() -> list[Periodo]:
    conn = repositorio.conectar()
    try:
        return repositorio.listar_periodos(conn)
    finally:
        conn.close()


def _escrever(acao) -> str | None:
    """Roda uma escrita curta no banco e devolve a mensagem de erro, se houver."""
    conn = repositorio.conectar()
    try:
        acao(conn)
    except repositorio.PeriodoDuplicado as erro:
        return f"Já existe um período chamado '{erro}'."
    except (ValueError, repositorio.PeriodoDesconhecido) as erro:
        return str(erro)
    finally:
        conn.close()
    st.cache_data.clear()
    return None


def _numero(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# ================================================================ cabeçalho
st.title("Limiar")
st.caption(
    "Fluxo de pessoas nas entradas — porta, instante e direção. "
    "Sem rosto, sem nome."
)

# ================================================================== filtros
with st.sidebar:
    st.header("Filtros")

    periodos = _periodos()
    nomes = [p.nome for p in periodos]
    escolha_periodo = st.selectbox(
        "Período de teste", ["(por datas)"] + nomes,
        help="Um período é um nome sobre um intervalo: 'Teste de campo 03/09', "
             "'Laboratório de física'. Escolha um para ver só aquele trecho.",
    )
    periodo = next((p for p in periodos if p.nome == escolha_periodo), None)

    if periodo is None:
        hoje = date.today()
        datas = st.date_input(
            "Período", value=(hoje - timedelta(days=14), hoje), format="DD/MM/YYYY"
        )
        # O date_input devolve tupla com o intervalo, mas devolve data unica
        # enquanto o usuario ainda nao escolheu o segundo limite.
        intervalo = isinstance(datas, tuple) and len(datas) == 2
        inicio, fim = datas if intervalo else (datas, datas)
    else:
        inicio, fim = periodo.datas()
        st.caption(periodo.rotulo())

    opcoes = ["(todas)"] + _cameras()
    pre = opcoes.index(periodo.camera_id) if periodo and periodo.camera_id in opcoes else 0
    escolha = st.selectbox("Entrada", opcoes, index=pre)
    camera = None if escolha == "(todas)" else escolha

    origem = st.radio(
        "Origem dos dados",
        [Origem.VISAO.value, Origem.SINTETICO.value],
        help="VISAO veio de câmera. SINTETICO é simulação, para desenvolver sem hardware.",
    )

    with st.expander("Períodos de teste"):
        aberto = next((p for p in periodos if p.aberto), None)
        if aberto is not None:
            st.caption(f"Em andamento: **{aberto.nome}**")
            if st.button(f"Encerrar '{aberto.nome}' agora"):
                erro = _escrever(lambda c: repositorio.encerrar_periodo(c, aberto.id))
                if erro:
                    st.error(erro)
                else:
                    st.rerun()
        with st.form("novo_periodo", clear_on_submit=True):
            nome_novo = st.text_input("Nome do novo período")
            camera_nova = st.selectbox("Entrada do período", opcoes, key="camera_periodo")
            if st.form_submit_button("Começar agora"):
                erro = _escrever(lambda c: repositorio.criar_periodo(
                    c, nome_novo, datetime.now(FUSO_LOCAL),
                    camera_id=None if camera_nova == "(todas)" else camera_nova,
                ))
                if erro:
                    st.error(erro)
                else:
                    st.rerun()
        if periodos:
            with st.form("renomear_periodo", clear_on_submit=True):
                alvo = st.selectbox("Renomear", nomes, key="periodo_renomear")
                novo_nome = st.text_input("Novo nome")
                if st.form_submit_button("Renomear"):
                    erro = _escrever(lambda c: repositorio.renomear_periodo(c, alvo, novo_nome))
                    if erro:
                        st.error(erro)
                    else:
                        st.rerun()

df = _carregar(inicio, fim, camera, origem)
if periodo is not None:
    df = consultas.recortar(df, "instante", periodo.inicio, periodo.fim)

with st.sidebar, st.expander("Exportar"):
    rotulo_arquivo = (periodo.nome if periodo else f"{inicio}_{fim}").replace(" ", "_")
    st.download_button(
        "Eventos filtrados (.csv)",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"limiar_{rotulo_arquivo}.csv", mime="text/csv",
        disabled=df.empty, use_container_width=True,
    )
    if st.button("Preparar cópia do banco", use_container_width=True):
        # Pela API de backup do sqlite, consistente mesmo com o serviço
        # escrevendo — copiar o arquivo por fora daria cópia corrompida às vezes.
        destino = config.CAMINHO_BACKUPS / "fluxo-copia-painel.db"
        backup.fazer_backup(config.CAMINHO_BANCO, destino)
        st.session_state["copia_banco"] = destino.read_bytes()
    if "copia_banco" in st.session_state:
        st.download_button(
            "Baixar fluxo.db", st.session_state["copia_banco"],
            file_name=f"fluxo-{date.today().isoformat()}.db",
            mime="application/octet-stream", use_container_width=True,
        )

if origem == Origem.SINTETICO.value:
    st.warning(
        "Exibindo **dados sintéticos**. Servem para desenvolver e demonstrar o painel "
        "sem câmera instalada, e não representam movimento real.",
        icon="⚠️",
    )

aba_fluxo, aba_pessoas, aba_vivo = st.tabs(["Fluxo", "Pessoas", "Ao vivo"])

# ====================================================================== Fluxo
with aba_fluxo:
    if df.empty:
        st.info(
            "Nenhum evento no período.\n\n"
            "- Para dados reais: `python scripts/processar_video.py --camera entrada_a`\n"
            "- Para simulação: `python scripts/simular_dia.py --dias 14` e escolha "
            "SINTETICO ao lado."
        )
    else:
        resumo = consultas.resumo_diario(df)
        entradas = int(resumo["entradas"].sum())
        saidas = int(resumo["saidas"].sum())
        dias = int(resumo["data_ref"].nunique())
        pico = consultas.pico_do_dia(df)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entradas", _numero(entradas))
        c2.metric("Saídas", _numero(saidas))
        c3.metric("Média por dia", _numero(entradas // dias) if dias else "—")
        c4.metric("Hora de pico", f"{pico[0]:02d}h" if pico else "—",
                  f"{pico[1]} entradas" if pico else None)

        saldo = entradas - saidas
        if entradas and abs(saldo) > 0.10 * entradas:
            st.warning(
                f"Saldo do período: **{saldo:+d}**. Entradas e saídas deveriam quase fechar. "
                f"Um desvio grande indica passagens não detectadas — vale conferir o vídeo "
                f"anotado.",
                icon="📐",
            )

        st.divider()

        esq, dir_ = st.columns([3, 2])

        with esq:
            st.subheader("Movimento por hora do dia")
            serie = consultas.serie_horaria(df).set_index("hora")
            st.bar_chart(serie[["entradas", "saidas"]], height=300)
            st.caption(
                "Somado no período. É a curva que define escala de portaria e horário de limpeza."
            )

        with dir_:
            st.subheader("Uso de cada entrada")
            comparativo = consultas.comparativo_portas(df)
            st.dataframe(
                comparativo.rename(columns={
                    "camera_id": "Entrada", "total": "Passagens", "participacao": "% do total"
                }),
                hide_index=True, use_container_width=True,
            )
            st.caption("Desbalanceamento grande costuma ser sinalização mal resolvida.")

        st.subheader("Volume por dia")
        por_dia = resumo.groupby("data_ref")[["entradas", "saidas"]].sum()
        st.line_chart(por_dia, height=280)

        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Ocupação estimada ao longo do dia")
            dias_disponiveis = sorted(df["data_ref"].dt.date.unique(), reverse=True)
            dia = st.selectbox(
                "Dia", dias_disponiveis, format_func=lambda d: d.strftime("%d/%m/%Y")
            )
            curva = consultas.ocupacao_do_dia(df, dia)
            if curva.empty:
                st.info("Sem eventos nesse dia.")
            else:
                st.line_chart(curva.set_index("instante")["ocupacao"], height=260)
                st.caption(
                    "Entradas acumuladas menos saídas. É **estimativa**: uma saída não detectada "
                    "mantém a curva alta pelo resto do dia."
                )

        with col_b:
            st.subheader("Média por dia da semana")
            media = consultas.media_por_dia_da_semana(df)
            if media.empty:
                st.info("Sem dados suficientes.")
            else:
                st.bar_chart(media.set_index("nome")["media_entradas"], height=260)
                st.caption("Base para planejar evento, prova e escala em dia fraco.")

        with st.expander("Eventos brutos"):
            st.dataframe(
                df[["instante", "camera_id", "direcao", "track_id_local", "confianca"]]
                .rename(columns={
                    "instante": "Instante", "camera_id": "Entrada", "direcao": "Direção",
                    "track_id_local": "Track", "confianca": "Confiança",
                }),
                hide_index=True, use_container_width=True, height=320,
            )
            st.caption(f"{len(df)} eventos.")

# ==================================================================== Pessoas
with aba_pessoas:
    pessoas, vinculos = _carregar_identidade(inicio, fim, camera)
    if periodo is not None:
        pessoas = consultas.recortar(pessoas, "primeiro_visto", periodo.inicio, periodo.fim)
        vinculos = consultas.recortar(vinculos, "instante", periodo.inicio, periodo.fim)

    if pessoas.empty:
        st.info(
            "Nenhuma identidade no período. A Etapa 2 roda por um script próprio:\n\n"
            "`python scripts/identificar_pessoas.py <camera>`"
        )
    else:
        st.caption(
            "Pseudônimos do dia (P1, P2…), reconhecidos pela aparência — roupa e silhueta. "
            "Valem só naquele dia, e não há rosto nem nome por trás deles."
        )
        r = consultas.resumo_identidade(pessoas, vinculos)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pessoas únicas", _numero(r["unicos"]),
                  f"{r['reentradas']} reentradas" if r["reentradas"] else None)
        c2.metric("Saídas sem par", _numero(r["sem_par"]),
                  f"{r['taxa_sem_par']:.0%} das saídas" if r["saidas"] else None,
                  delta_color="inverse")
        c3.metric("Permanência média",
                  f"{r['permanencia_media_min']:.0f} min" if r["permanencias"] else "—",
                  f"{r['permanencias']} pares" if r["permanencias"] else None)
        c4.metric("Ainda dentro",
                  _numero(int((pessoas["entradas"] > pessoas["saidas"]).sum())))

        if r["saidas"] and r["taxa_sem_par"] > 0.30:
            st.warning(
                f"**{r['taxa_sem_par']:.0%}** das saídas ficaram sem par. Ou a aparência "
                f"não está separando as pessoas, ou o limiar está alto. Meça antes de ajustar: "
                f"`python scripts/reprocessar_identidade.py <camera> --varredura`.",
                icon="🔎",
            )

        st.divider()
        esq, dir_ = st.columns([2, 3])

        with esq:
            st.subheader("Tempo de permanência")
            perms = consultas.permanencias(vinculos)
            if perms.empty:
                st.info("Nenhum par entrada→saída ainda.")
            else:
                faixas = pd.cut(
                    perms["minutos"],
                    bins=[0, 15, 30, 60, 120, 240, 480, 1e9],
                    labels=["<15", "15-30", "30-60", "1-2h", "2-4h", "4-8h", ">8h"],
                    right=False,
                )
                st.bar_chart(faixas.value_counts().sort_index(), height=280)
                st.caption("Pares entrada→saída do mesmo pseudônimo, em faixas.")

        with dir_:
            st.subheader("Quem passou")
            tabela = pessoas[[
                "data_ref", "pseudonimo", "apelido", "primeiro_visto", "ultimo_visto",
                "entradas", "saidas",
            ]].copy()
            tabela["data_ref"] = tabela["data_ref"].dt.strftime("%d/%m")
            for coluna in ("primeiro_visto", "ultimo_visto"):
                tabela[coluna] = tabela[coluna].dt.strftime("%H:%M")
            # O apelido só existe no teste de validação. Sem nenhum, a coluna
            # nem aparece — em operação, ninguém tem nome aqui.
            if tabela["apelido"].isna().all():
                tabela = tabela.drop(columns=["apelido"])
            st.dataframe(
                tabela.rename(columns={
                    "data_ref": "Dia", "pseudonimo": "P", "apelido": "Apelido (teste)",
                    "primeiro_visto": "Primeira", "ultimo_visto": "Última",
                    "entradas": "Entradas", "saidas": "Saídas",
                }),
                hide_index=True, use_container_width=True, height=320,
            )

        with st.expander("Vínculos brutos"):
            st.dataframe(
                vinculos[[
                    "instante", "camera_id", "direcao", "pseudonimo", "metodo", "similaridade",
                ]].rename(columns={
                    "instante": "Instante", "camera_id": "Entrada", "direcao": "Direção",
                    "pseudonimo": "P", "metodo": "Método", "similaridade": "Similaridade",
                }),
                hide_index=True, use_container_width=True, height=320,
            )
            st.caption(f"{len(vinculos)} vínculos. P vazio = saída sem par.")

# ==================================================================== Ao vivo
with aba_vivo:
    st.caption(
        "O último quadro que o agente processou, com as caixas e a linha. "
        "É um espelho, não uma gravação: o arquivo de agora apaga o de antes."
    )

    @st.fragment(run_every=0.5)
    def _ao_vivo() -> None:
        if camera:
            candidatas = [camera]
        else:
            candidatas = [
                c for c in _cameras() if (config.CAMINHO_QUADROS / f"{c}.jpg").exists()
            ]
        if not candidatas:
            st.info(
                "Nenhuma câmera publicando quadro. O agente está de pé? "
                "(`python scripts/rodar_tudo.py entrada_real`)"
            )
            return
        colunas = st.columns(len(candidatas))
        for coluna, cam in zip(colunas, candidatas, strict=True):
            arquivo = config.CAMINHO_QUADROS / f"{cam}.jpg"
            idade = idade_do_quadro(arquivo)
            with coluna:
                if idade is None:
                    st.info(f"**{cam}**: nenhum quadro publicado ainda.")
                    continue
                try:
                    imagem = arquivo.read_bytes()
                except OSError:
                    # Trocado bem no instante da leitura: o próximo ciclo pega.
                    continue
                if idade > QUADRO_VELHO_S:
                    st.warning(
                        f"**{cam}**: sem quadro novo há {idade:.0f} s. "
                        "Câmera fora do ar ou agente parado — veja o log.",
                        icon="⏸️",
                    )
                    st.image(imagem, use_container_width=True)
                else:
                    st.image(imagem, caption=f"{cam} — há {idade:.1f} s",
                             use_container_width=True)

    _ao_vivo()
