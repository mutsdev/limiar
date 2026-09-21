"""Produto vetorial decidindo quem entrou pela porta — versão de aula.

MATERIAL DIDÁTICO. A fonte da verdade continua sendo
`src/fluxo/contagem/geometria.py`; este arquivo é uma cópia com o resto do
sistema removido (YOLO, banco, agente, rastreador) e com desenho, para dar
para mexer numa função e ver o resultado na hora.

As funções abaixo são as MESMAS do projeto, com os mesmos nomes e a mesma
matemática. Se alguma divergir, o errado é este arquivo — há um teste no fim
(`conferir_contra_o_projeto`) que compara os dois lado a lado.

    python geometria_aula.py                  # todos os cenários
    python geometria_aula.py --cenario porta  # um só
    python geometria_aula.py --conferir       # compara com o código real
    python geometria_aula.py --escuro         # paleta dos slides, fundo preto

--------------------------------------------------------------------------
A IDEIA EM UMA FRASE

Dois vetores saem do ponto A: um vai até B (a linha desenhada na porta) e o
outro vai até P (a pessoa). O produto vetorial AB × AP é perpendicular aos
dois — ou seja, perpendicular à tela. Ele aponta para fora da tela ou para
dentro dela, e é isso que responde "a pessoa está de que lado?".

--------------------------------------------------------------------------
POR QUE EM 2D O PRODUTO VETORIAL "VIRA UM NÚMERO"

Ele não vira número nenhum: continua sendo um vetor, mas com duas componentes
sempre nulas. Pondo os dois vetores no plano z = 0:

    (x1, y1, 0) × (x2, y2, 0) = ( y1·0 − 0·y2 ,  0·x2 − x1·0 ,  x1·y2 − x2·y1 )
                              = ( 0 , 0 , x1·y2 − x2·y1 )

Sobra a componente z. É ela que a função `produto_vetorial` devolve, e é por
isso que o docstring do projeto diz "componente z" e não "produto vetorial".

(Quem já viu determinantes reconhece x1·y2 − x2·y1 como |x1 x2; y1 y2|. É a
mesma conta, e é assim que se calcula na prática — mas o que esse número É
continua sendo a terceira componente de um produto vetorial.)

--------------------------------------------------------------------------
A ARMADILHA DAS COORDENADAS DE IMAGEM

Em matemática o eixo y aponta para CIMA. Em imagem, ele aponta para BAIXO: o
pixel (0,0) é o canto superior esquerdo. A fórmula é a mesma, mas o sentido
visual da rotação inverte — o que a conta chama de "sentido anti-horário"
aparece na tela como horário.

Por isso o projeto NÃO tenta deduzir qual lado é "dentro do prédio". Ele mede:
`lado_dentro` sai da calibração, e o docstring de `LinhaDeContagem` diz
"depende de como a câmera foi montada". Os cenários aqui mostram os dois
sistemas, para a diferença ficar visível em vez de virar bug.
"""

from __future__ import annotations

import argparse
import sys
from math import hypot

Ponto = tuple[float, float]
Caixa = tuple[float, float, float, float]

# Tolerância para comparar float com zero. Coordenadas são em pixels, então
# qualquer coisa abaixo disso é ruído de arredondamento, não geometria.
EPS = 1e-9


# ==========================================================================
# A MATEMÁTICA — idêntica a src/fluxo/contagem/geometria.py
# ==========================================================================


def produto_vetorial(a: Ponto, b: Ponto, p: Ponto) -> float:
    """Componente z do produto vetorial (B−A) × (P−A).

        AB = B − A = (bx − ax, by − ay)
        AP = P − A = (px − ax, py − ay)

        AB × AP = (0, 0, (bx−ax)·(py−ay) − (by−ay)·(px−ax))
                              \\_______________________________/
                                        é isto que volta

    O SINAL diz de que lado da reta AB o ponto P está.
    O MÓDULO é a área do paralelogramo de lados AB e AP — usada logo abaixo
    para a distância até a reta.
    """
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def lado(a: Ponto, b: Ponto, p: Ponto) -> int:
    """+1, −1 ou 0 (sobre a reta).

    Toda a contagem de pessoas do projeto se apoia neste sinal. A pessoa
    "cruzou" quando ele troca — e só então as outras salvaguardas entram.
    """
    v = produto_vetorial(a, b, p)
    if v > EPS:
        return 1
    if v < -EPS:
        return -1
    return 0


def distancia_ponto_reta(p: Ponto, a: Ponto, b: Ponto) -> float:
    """Distância perpendicular de P à reta AB, em pixels.

    Sai do MÓDULO do mesmo produto vetorial. A área de um paralelogramo é
    base × altura:

        ‖AB × AP‖ = ‖AB‖ · ‖AP‖ · sen θ = base · altura

    Tomando AB como base, a altura é exatamente a distância que se quer:

        distância = ‖AB × AP‖ / ‖AB‖

    Um produto vetorial, dois usos: o sinal decide o lado, o módulo decide se
    dá para confiar na decisão (a "zona morta" de 15 px do projeto).
    """
    comprimento = hypot(b[0] - a[0], b[1] - a[1])
    if comprimento < EPS:
        # Linha degenerada (A == B): não há direção, então a "distância à
        # reta" vira a distância ao ponto.
        return hypot(p[0] - a[0], p[1] - a[1])
    return abs(produto_vetorial(a, b, p)) / comprimento


def _no_retangulo(p: Ponto, q: Ponto, r: Ponto) -> bool:
    """Q está na caixa envolvente do segmento PR (usado no caso colinear)."""
    return (
        min(p[0], r[0]) - EPS <= q[0] <= max(p[0], r[0]) + EPS
        and min(p[1], r[1]) - EPS <= q[1] <= max(p[1], r[1]) + EPS
    )


def segmentos_se_cruzam(p1: Ponto, p2: Ponto, a: Ponto, b: Ponto) -> bool:
    """O deslocamento P1→P2 cruza o SEGMENTO AB?

    Quatro produtos vetoriais. A ideia: dois segmentos se cruzam quando cada
    um "separa" as pontas do outro —

        A e B ficam em lados opostos da reta P1P2   (o1 != o2)
        P1 e P2 ficam em lados opostos da reta AB   (o3 != o4)

    A distinção entre SEGMENTO e RETA INFINITA é essencial: sem ela, alguém
    passando muito à esquerda da porta — fora da linha desenhada, mas ainda
    do outro lado da reta que a contém — seria contado como se tivesse
    entrado. Ver o cenário `fora_do_segmento`.
    """
    o1 = lado(p1, p2, a)
    o2 = lado(p1, p2, b)
    o3 = lado(a, b, p1)
    o4 = lado(a, b, p2)

    if o1 != o2 and o3 != o4:
        return True

    # Casos colineares (produto vetorial = 0): o ponto toca o segmento sem
    # atravessá-lo. Aqui o sinal não decide nada, e é preciso olhar se o
    # ponto cai dentro da caixa envolvente.
    if o1 == 0 and _no_retangulo(p1, a, p2):
        return True
    if o2 == 0 and _no_retangulo(p1, b, p2):
        return True
    if o3 == 0 and _no_retangulo(a, p1, b):
        return True
    if o4 == 0 and _no_retangulo(a, p2, b):
        return True

    return False


def ponto_base(caixa: Caixa) -> Ponto:
    """Centro da base da caixa: onde a pessoa toca o chão.

    Combinação convexa (peso 1/2) das duas bordas verticais, descartando a
    altura. O centro da caixa oscila quando a pessoa levanta o braço ou é
    ocluída no topo; o pé fica no mesmo plano em que a linha foi desenhada.
    """
    x1, _, x2, y2 = caixa
    return ((x1 + x2) / 2.0, y2)


def distancia(p: Ponto, q: Ponto) -> float:
    """Distância euclidiana entre dois pontos, em pixels."""
    return hypot(q[0] - p[0], q[1] - p[1])


# ==========================================================================
# DESENHO
# ==========================================================================


def _matplotlib():
    try:
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        sys.exit(
            "Este arquivo desenha com matplotlib, que nao esta instalado neste Python.\n"
            "  Com o ambiente do projeto:  uv run docs/aula-algebra-linear/geometria_aula.py\n"
            "  Ou instale:                 pip install matplotlib\n"
            "As funcoes matematicas acima nao dependem dele e funcionam sem nada instalado."
        )


COR_LINHA = "#e8890c"
COR_POS = "#1a7f37"
COR_NEG = "#cf222e"
COR_ZERO = "#57606a"
COR_VETOR = "#0969da"
COR_TRAJETO = "#8250df"
COR_FUNDO = "white"       # contorno dos discos e fundo das caixas de texto
COR_CAIXA = "#f6f8fa"
COR_CAIXA_BORDA = "#d0d7de"


def usar_tema_escuro(plt) -> None:
    """Mesma paleta dos slides.html: fundo preto, cores mais vivas."""
    global COR_LINHA, COR_POS, COR_NEG, COR_ZERO, COR_VETOR, COR_TRAJETO
    global COR_FUNDO, COR_CAIXA, COR_CAIXA_BORDA
    plt.style.use("dark_background")
    plt.rcParams.update({
        "figure.facecolor": "#000000", "axes.facecolor": "#0e1116",
        "savefig.facecolor": "#000000", "axes.edgecolor": "#262c35",
        "grid.color": "#262c35", "text.color": "#e6eaef",
        "axes.labelcolor": "#9aa4af", "xtick.color": "#9aa4af", "ytick.color": "#9aa4af",
    })
    COR_LINHA, COR_POS, COR_NEG = "#ffb020", "#3fd06a", "#ff5c5c"
    COR_ZERO, COR_VETOR, COR_TRAJETO = "#9aa4af", "#5ab0ff", "#c69bff"
    COR_FUNDO, COR_CAIXA, COR_CAIXA_BORDA = "#000000", "#0e1116", "#262c35"


def _sinal(s: int) -> str:
    """"+1", "-1" ou "0" — porque zero com sinal ("+0") nao existe."""
    return f"{s:+d}" if s else "0"


def _cor_do_lado(s: int) -> str:
    return {1: COR_POS, -1: COR_NEG, 0: COR_ZERO}[s]


def desenhar(
    ax,
    a: Ponto,
    b: Ponto,
    p: Ponto,
    titulo: str = "",
    y_para_baixo: bool = False,
    mostrar_paralelogramo: bool = True,
    trajeto: list[Ponto] | None = None,
    aspecto_igual: bool = True,
) -> None:
    """Uma cena: a linha AB, o ponto P, os vetores e o perpendicular.

    `y_para_baixo=True` desenha em coordenadas de IMAGEM (origem no canto
    superior esquerdo), como o sistema real trabalha. O símbolo do
    perpendicular leva isso em conta: com o eixo y invertido, o mesmo sinal
    algébrico corresponde ao sentido oposto na tela.
    """
    v = produto_vetorial(a, b, p)
    s = lado(a, b, p)
    d = distancia_ponto_reta(p, a, b)

    # O paralelogramo de lados AB e AP: A, A+AB, A+AB+AP, A+AP.
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    if mostrar_paralelogramo and abs(v) > EPS:
        cantos = [
            a,
            (a[0] + ab[0], a[1] + ab[1]),
            (a[0] + ab[0] + ap[0], a[1] + ab[1] + ap[1]),
            (a[0] + ap[0], a[1] + ap[1]),
        ]
        ax.fill(
            [c[0] for c in cantos], [c[1] for c in cantos],
            color=_cor_do_lado(s), alpha=0.10, zorder=1,
        )

    if trajeto:
        ax.plot(
            [q[0] for q in trajeto], [q[1] for q in trajeto],
            color=COR_TRAJETO, lw=1.2, ls=":", marker="o", ms=3, zorder=2,
            label="trajeto",
        )

    # A linha da porta: segmento grosso, com as pontas marcadas.
    ax.plot([a[0], b[0]], [a[1], b[1]], color=COR_LINHA, lw=3.5, zorder=3)
    ax.scatter([a[0], b[0]], [a[1], b[1]], color=COR_LINHA, s=45, zorder=4)
    ax.annotate("A", a, textcoords="offset points", xytext=(-14, -4),
                fontsize=11, weight="bold", color=COR_LINHA)
    ax.annotate("B", b, textcoords="offset points", xytext=(8, -4),
                fontsize=11, weight="bold", color=COR_LINHA)

    # Os dois vetores que entram na conta, desenhados como setas a partir de A.
    for (dx, dy), nome in ((ab, "AB"), (ap, "AP")):
        ax.annotate(
            "", xy=(a[0] + dx, a[1] + dy), xytext=a,
            arrowprops=dict(arrowstyle="-|>", lw=1.8, color=COR_VETOR,
                            shrinkA=0, shrinkB=0, alpha=0.85),
            zorder=5,
        )
        ax.annotate(nome, (a[0] + dx * 0.55, a[1] + dy * 0.55),
                    textcoords="offset points", xytext=(6, 6),
                    fontsize=10, color=COR_VETOR, weight="bold")

    ax.scatter([p[0]], [p[1]], color=_cor_do_lado(s), s=110, zorder=6,
               edgecolors=COR_FUNDO, linewidths=1.5)
    ax.annotate("P", p, textcoords="offset points", xytext=(9, 6),
                fontsize=11, weight="bold", color=_cor_do_lado(s))

    # O perpendicular. Com y para cima (matemática), z > 0 sai da tela.
    # Com y para baixo (imagem), o eixo inverte e z > 0 entra na tela.
    if s == 0:
        # Produto vetorial nulo: nao ha perpendicular para desenhar. O resumo
        # abaixo diz "sobre a linha", e um simbolo aqui so confundiria.
        sentido = "sobre a linha"
    else:
        sai = (s > 0) if not y_para_baixo else (s < 0)
        meio = ((a[0] + b[0] + p[0]) / 3.0, (a[1] + b[1] + p[1]) / 3.0)
        ax.annotate("⊙" if sai else "⊗", meio, fontsize=26, ha="center",
                    va="center", color=_cor_do_lado(s), zorder=7)
        sentido = "sai da tela" if sai else "entra na tela"

    ax.set_title(titulo, fontsize=11, weight="bold", loc="left")
    resumo = (
        f"AB × AP = {v:+,.1f}   →  lado {_sinal(s)}  ({sentido})\n"
        f"distância à reta = |{abs(v):,.1f}| / ‖AB‖ = {d:.1f} px"
    )
    ax.text(
        0.02, 0.02, resumo, transform=ax.transAxes, fontsize=8.5,
        va="bottom", family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", fc=COR_CAIXA, ec=COR_CAIXA_BORDA, alpha=0.9),
    )
    if aspecto_igual:
        ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.18)
    ax.grid(True, alpha=0.15)
    if y_para_baixo and not ax.yaxis_inverted():
        ax.invert_yaxis()


# ==========================================================================
# CENÁRIOS — cada um prova um ponto da aula
# ==========================================================================

# A linha de teste do projeto (tests/test_geometria.py): vertical em x = 450.
A_TESTE: Ponto = (450.0, 30.0)
B_TESTE: Ponto = (450.0, 240.0)

# A linha real da porta da faculdade (config/cameras.yaml, entrada_real),
# em pixels de um quadro VGA 640×480 da ESP32.
A_PORTA: Ponto = (253.0, 447.0)
B_PORTA: Ponto = (458.0, 438.0)


def cenario_sinal(plt):
    """O básico: o sinal do produto vetorial é o lado."""
    fig, eixos = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        "O sinal de AB × AP é o lado — eixo y para cima (convenção da matemática)",
        fontsize=13, weight="bold",
    )
    for ax, p, titulo in zip(
        eixos,
        [(200.0, 100.0), (450.0, 100.0), (700.0, 100.0)],
        ["P à esquerda de AB", "P sobre a reta", "P à direita de AB"],
        strict=True,
    ):
        desenhar(ax, A_TESTE, B_TESTE, p, titulo)
    fig.tight_layout()
    return fig


def cenario_fora_do_segmento(plt):
    """Reta infinita × segmento — o erro que a distinção evita.

    Desenhado à mão, sem os vetores AB/AP: aqui o assunto é o TRAJETO contra
    o SEGMENTO, e as setas do produto vetorial só competiriam com ele.
    """
    fig, ax = plt.subplots(figsize=(11, 7))

    # A reta que CONTÉM o segmento, prolongada bem além dele.
    ax.plot([450, 450], [-150, 620], color=COR_LINHA, lw=1.2, ls="--",
            alpha=0.55, zorder=1)
    ax.annotate("a reta que contém a linha\n(infinita — não é a porta)",
                (450, 585), textcoords="offset points", xytext=(12, 0),
                fontsize=9.5, color=COR_LINHA, va="center", style="italic")

    # O SEGMENTO desenhado na calibração: só isto é a porta.
    ax.plot([A_TESTE[0], B_TESTE[0]], [A_TESTE[1], B_TESTE[1]],
            color=COR_LINHA, lw=5, zorder=3, solid_capstyle="butt")
    ax.scatter([A_TESTE[0], B_TESTE[0]], [A_TESTE[1], B_TESTE[1]],
               color=COR_LINHA, s=60, zorder=4)
    ax.annotate("A", A_TESTE, textcoords="offset points", xytext=(-20, -3),
                fontsize=12, weight="bold", color=COR_LINHA)
    ax.annotate("B", B_TESTE, textcoords="offset points", xytext=(-20, -3),
                fontsize=12, weight="bold", color=COR_LINHA)
    ax.annotate("o segmento AB\né a porta", (450, 200),
                textcoords="offset points", xytext=(-108, 0), fontsize=10.5,
                weight="bold", color=COR_LINHA, va="center", ha="center")

    trajetos = [
        ((380.0, 130.0), (520.0, 130.0), "passa PELA porta"),
        ((380.0, 430.0), (520.0, 430.0), "passa LONGE da porta"),
    ]
    for p1, p2, rotulo in trajetos:
        cruzou = segmentos_se_cruzam(p1, p2, A_TESTE, B_TESTE)
        cor = COR_POS if cruzou else COR_NEG
        ax.annotate("", xy=p2, xytext=p1,
                    arrowprops=dict(arrowstyle="-|>", lw=2.6, color=cor),
                    zorder=5)
        ax.scatter([p1[0], p2[0]], [p1[1], p2[1]], color=cor, s=70, zorder=6,
                   edgecolors=COR_FUNDO, linewidths=1.4)
        s1 = lado(A_TESTE, B_TESTE, p1)
        s2 = lado(A_TESTE, B_TESTE, p2)
        ax.annotate(
            rotulo + "\nlado: " + f"{_sinal(s1)} → {_sinal(s2)}" + "  (trocou!)\n"
            + f"segmentos_se_cruzam = {cruzou}",
            p2, textcoords="offset points", xytext=(16, 0),
            fontsize=10, family="monospace", weight="bold", color=cor,
            va="center",
            bbox=dict(boxstyle="round,pad=0.4", fc=COR_CAIXA, ec=cor, alpha=0.95),
        )

    ax.set_title("Os DOIS trajetos trocam de lado. Só um passou pela porta.",
                 fontsize=13.5, weight="bold", loc="left")
    ax.text(
        0.5, -0.08,
        "É por isso que `segmentos_se_cruzam` testa o SEGMENTO e não a reta: o "
        "sinal do produto vetorial, sozinho,\nnão distingue quem entrou de quem "
        "passou a dois metros da porta.",
        transform=ax.transAxes, ha="center", va="top", fontsize=10.5,
    )
    ax.set_xlim(330, 720)
    ax.set_ylim(-60, 640)
    ax.grid(True, alpha=0.15)
    fig.tight_layout()
    return fig


def cenario_zona_morta(plt):
    """O módulo do produto vetorial em ação: 15 px de zona morta."""
    fig, ax = plt.subplots(figsize=(9, 6))
    zona = 15.0
    ax.axvspan(450 - zona, 450 + zona, color=COR_ZERO, alpha=0.13, zorder=0)
    p = (462.0, 120.0)
    desenhar(ax, A_TESTE, B_TESTE, p,
             "Zona morta: dentro da faixa, o sistema ADIA em vez de arriscar",
             mostrar_paralelogramo=False)
    d = distancia_ponto_reta(p, A_TESTE, B_TESTE)
    ax.text(
        0.5, 0.96,
        f"distância = {d:.1f} px  <  zona_morta_px = {zona:.0f}\n"
        "→ nada é contado neste quadro",
        transform=ax.transAxes, ha="center", va="top", fontsize=10,
        family="monospace", weight="bold", color=COR_ZERO,
        bbox=dict(boxstyle="round,pad=0.4", fc=COR_CAIXA, ec=COR_CAIXA_BORDA),
    )
    fig.tight_layout()
    return fig


def cenario_borda(plt):
    """Um pixel de cada lado — os casos que os testes do projeto fixam."""
    fig, eixos = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(
        "Um pixel decide: os casos de borda de tests/test_geometria.py",
        fontsize=13, weight="bold",
    )
    for ax, x in zip(eixos, [449.0, 450.0, 451.0], strict=True):
        p = (x, 100.0)
        s = lado(A_TESTE, B_TESTE, p)
        desenhar(ax, A_TESTE, B_TESTE, p, f"P = ({x:.0f}, 100)  →  lado = {_sinal(s)}",
                 mostrar_paralelogramo=False, aspecto_igual=False)
        ax.set_xlim(430, 470)
        ax.set_ylim(60, 160)
    fig.tight_layout()
    return fig


def cenario_porta(plt):
    """A porta real, em coordenadas de imagem (y para baixo)."""
    fig, eixos = plt.subplots(1, 2, figsize=(13, 6))
    fig.suptitle(
        "A linha real da porta (config/cameras.yaml) — coordenadas de IMAGEM, "
        "y para baixo",
        fontsize=13, weight="bold",
    )
    trajeto = [(300.0, 380.0), (320.0, 410.0), (340.0, 445.0), (355.0, 480.0)]
    for ax, p, titulo in zip(
        eixos,
        [(330.0, 400.0), (355.0, 480.0)],
        ["Antes de cruzar", "Depois de cruzar"],
        strict=True,
    ):
        desenhar(ax, A_PORTA, B_PORTA, p, titulo, y_para_baixo=True,
                 mostrar_paralelogramo=False, trajeto=trajeto)
    cruzou = segmentos_se_cruzam(trajeto[0], trajeto[-1], A_PORTA, B_PORTA)
    eixos[1].text(
        0.5, 0.96, f"segmentos_se_cruzam = {cruzou}",
        transform=eixos[1].transAxes, ha="center", va="top", fontsize=11,
        family="monospace", weight="bold", color=COR_POS if cruzou else COR_NEG,
        bbox=dict(boxstyle="round,pad=0.4", fc=COR_CAIXA, ec=COR_CAIXA_BORDA),
    )
    fig.tight_layout()
    return fig


def cenario_diagonal(plt):
    """Linha diagonal: nada na matemática exige que ela seja vertical."""
    fig, ax = plt.subplots(figsize=(9, 7))
    a, b = (100.0, 100.0), (400.0, 400.0)
    trajeto = [(120.0, 350.0), (200.0, 300.0), (300.0, 200.0), (360.0, 150.0)]
    desenhar(ax, a, b, trajeto[-1],
             "Linha diagonal: a mesma conta, sem nenhum caso especial",
             trajeto=trajeto)
    ax.text(
        0.5, 0.96,
        f"lado(início) = {_sinal(lado(a, b, trajeto[0]))}   "
        f"lado(fim) = {_sinal(lado(a, b, trajeto[-1]))}   "
        f"cruzou = {segmentos_se_cruzam(trajeto[0], trajeto[-1], a, b)}",
        transform=ax.transAxes, ha="center", va="top", fontsize=10,
        family="monospace", weight="bold",
        bbox=dict(boxstyle="round,pad=0.4", fc=COR_CAIXA, ec=COR_CAIXA_BORDA),
    )
    fig.tight_layout()
    return fig


CENARIOS = {
    "sinal": cenario_sinal,
    "fora_do_segmento": cenario_fora_do_segmento,
    "zona_morta": cenario_zona_morta,
    "borda": cenario_borda,
    "porta": cenario_porta,
    "diagonal": cenario_diagonal,
}


# ==========================================================================
# CONFERÊNCIA CONTRA O CÓDIGO DE PRODUÇÃO
# ==========================================================================


def conferir_contra_o_projeto() -> int:
    """Roda as funções daqui e as do projeto sobre os mesmos casos.

    Material didático que diverge do código ensina errado. Se este arquivo
    for editado numa aula, isto diz na hora se a matemática ainda bate.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(raiz / "src"))
    try:
        from fluxo.contagem import geometria as real
    except ImportError:
        print("Nao achei o pacote `fluxo` — rode a partir do repositorio.")
        return 1

    casos_ponto = [
        (A_TESTE, B_TESTE, (200.0, 100.0)),
        (A_TESTE, B_TESTE, (449.0, 100.0)),
        (A_TESTE, B_TESTE, (450.0, 100.0)),
        (A_TESTE, B_TESTE, (451.0, 100.0)),
        (A_TESTE, B_TESTE, (900.0, 100.0)),
        (A_TESTE, B_TESTE, (450.0, 1000.0)),
        (A_PORTA, B_PORTA, (330.0, 400.0)),
        (A_PORTA, B_PORTA, (355.0, 480.0)),
        ((0.0, 0.0), (0.0, 0.0), (3.0, 4.0)),
    ]
    casos_segmento = [
        ((380.0, 130.0), (520.0, 130.0), A_TESTE, B_TESTE),
        ((380.0, 400.0), (520.0, 400.0), A_TESTE, B_TESTE),
        ((380.0, 239.9), (520.0, 239.9), A_TESTE, B_TESTE),
        ((380.0, 240.1), (520.0, 240.1), A_TESTE, B_TESTE),
        ((380.0, 30.0), (520.0, 30.0), A_TESTE, B_TESTE),
        ((100.0, 100.0), (100.0, 100.0), A_TESTE, B_TESTE),
        ((120.0, 350.0), (360.0, 150.0), (100.0, 100.0), (400.0, 400.0)),
    ]

    falhas = 0
    for a, b, p in casos_ponto:
        for nome, meu, dele in (
            ("produto_vetorial", produto_vetorial(a, b, p), real.produto_vetorial(a, b, p)),
            ("lado", lado(a, b, p), real.lado(a, b, p)),
            ("distancia_ponto_reta",
             distancia_ponto_reta(p, a, b), real.distancia_ponto_reta(p, a, b)),
        ):
            if meu != dele:
                print(f"DIVERGE {nome}{(a, b, p)}: aula={meu} projeto={dele}")
                falhas += 1

    for p1, p2, a, b in casos_segmento:
        meu = segmentos_se_cruzam(p1, p2, a, b)
        dele = real.segmentos_se_cruzam(p1, p2, a, b)
        if meu != dele:
            print(f"DIVERGE segmentos_se_cruzam{(p1, p2, a, b)}: aula={meu} projeto={dele}")
            falhas += 1

    for caixa in [(100.0, 50.0, 180.0, 300.0), (0.0, 0.0, 10.0, 10.0)]:
        if ponto_base(caixa) != real.ponto_base(caixa):
            print(f"DIVERGE ponto_base{caixa}")
            falhas += 1

    total = len(casos_ponto) * 3 + len(casos_segmento) + 2
    if falhas:
        print(f"\n{falhas} divergencia(s) em {total} comparacoes.")
        return 1
    print(f"OK: {total} comparacoes, nenhuma divergencia entre a aula e o projeto.")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Produto vetorial decidindo quem entrou pela porta.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Cenarios: " + ", ".join(CENARIOS),
    )
    p.add_argument("--cenario", choices=sorted(CENARIOS), default=None,
                   help="Desenha um cenario so (padrao: todos)")
    p.add_argument("--conferir", action="store_true",
                   help="Compara com src/fluxo/contagem/geometria.py e sai")
    p.add_argument("--salvar", metavar="PASTA", default=None,
                   help="Salva PNG em vez de abrir janela")
    p.add_argument("--escuro", action="store_true",
                   help="Fundo preto, na paleta dos slides (para projetar)")
    args = p.parse_args()

    if args.conferir:
        sys.exit(conferir_contra_o_projeto())

    plt = _matplotlib()
    if args.escuro:
        usar_tema_escuro(plt)
    escolhidos = [args.cenario] if args.cenario else list(CENARIOS)
    for nome in escolhidos:
        fig = CENARIOS[nome](plt)
        if args.salvar:
            from pathlib import Path

            destino = Path(args.salvar)
            destino.mkdir(parents=True, exist_ok=True)
            caminho = destino / f"{nome}.png"
            fig.savefig(caminho, dpi=130, bbox_inches="tight")
            print(f"gravado {caminho}")
    if not args.salvar:
        plt.show()


if __name__ == "__main__":
    main()
