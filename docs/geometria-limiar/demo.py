"""Roda o contador didático sobre a trajetória real da pessoa 1 e gera as figuras.

    python demo.py              # tabela quadro a quadro + figuras/f1.png ... f6.png
    python demo.py --conferir   # compara com o código de produção do Limiar

Termina com três verificações: com zona morta de 15 px o evento sai no
quadro 542; com 0 px, no 540; com 30 px, no 544. São os números que o
código de produção (``LinhaDeContagem``) dá para a mesma trajetória.
"""

import csv
import sys
from datetime import datetime
from math import hypot
from pathlib import Path
from statistics import median

import geometria
from contador import Contador

AQUI = Path(__file__).resolve().parent
FIGURAS = AQUI / "figuras"

# A câmera da entrada: linha de config/cameras.yaml, quadro de 640 x 480.
A = (253.0, 447.0)
B = (458.0, 438.0)
LADO_DENTRO = 1
LARGURA, ALTURA = 640, 480
AB = (B[0] - A[0], B[1] - A[1])


def carregar():
    """Quadros da pessoa 1: (q, t em segundos desde o primeiro, caixa)."""
    linhas = list(csv.DictReader((AQUI / "pessoa1.csv").open(encoding="utf-8")))
    t0 = datetime.fromisoformat(linhas[0]["t"])
    return [
        (
            int(r["q"]),
            (datetime.fromisoformat(r["t"]) - t0).total_seconds(),
            tuple(float(r[k]) for k in ("x1", "y1", "x2", "y2")),
        )
        for r in linhas
    ]


def rodar(quadros, **parametros):
    """Passa a trajetória pelo contador e devolve os registros de cada quadro."""
    c = Contador(A, B, LADO_DENTRO, **parametros)
    registros = [c.passo(q, t, caixa) for q, t, caixa in quadros]
    return c, registros


def f(p):
    return f"({p[0]:.1f}, {p[1]:.1f})"


def y_reta(x):
    """Altura da reta AB em um x qualquer."""
    return A[1] + AB[1] * (x - A[0]) / AB[0]


def tabela(registros, ate=543):
    """A tabela do capítulo 7, em markdown."""
    print("| q | Δt (ms) | pé bruto | pé suavizado | cross (px²) | d (px) | lado | idade | lado conf. (antes) | âncora (antes) | decisão |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in registros:
        if r["q"] > ate:
            break
        conf = "—" if r["lado_confirmado"] is None else f"{r['lado_confirmado']:+d}"
        anc = "—" if r["ancora"] is None else f(r["ancora"])
        decisao = r["motivo"] + (f" → **{r['evento']}**" if r["evento"] else "")
        print(
            f"| {r['q']} | {r['t'] * 1000:.0f} | {f(r['bruto'])} | {f(r['suavizado'])} "
            f"| {r['cross']:+.0f} | {r['d']:.1f} | {r['lado']:+d} | {r['idade']} | {conf} | {anc} | {decisao} |"
        )


# --------------------------------------------------------------------- figuras

def figuras(quadros, registros):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    FIGURAS.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "figure.dpi": 150})
    COR_LINHA, COR_DENTRO, COR_FORA, COR_PE = "#c62828", "#1565c0", "#ef6c00", "#2e7d32"

    def quadro_vazio(ax, titulo):
        ax.set_xlim(0, LARGURA)
        ax.set_ylim(ALTURA, 0)          # y cresce para baixo, como na imagem
        ax.set_aspect("equal")
        ax.set_xlabel("x (px)")
        ax.set_ylabel("y (px) — cresce para baixo")
        ax.set_title(titulo, fontsize=10)
        ax.grid(alpha=0.2)

    def linha_ab(ax, rotulo=True):
        ax.annotate("", xy=B, xytext=A, arrowprops=dict(arrowstyle="->", color=COR_LINHA, lw=2.5))
        if rotulo:
            ax.annotate("A (253, 447)", A, xytext=(-72, 12), textcoords="offset points", color=COR_LINHA)
            ax.annotate("B (458, 438)", B, xytext=(6, 12), textcoords="offset points", color=COR_LINHA)

    def reta_inteira(ax):
        ax.plot([0, LARGURA], [y_reta(0), y_reta(LARGURA)], color=COR_LINHA, lw=0.8, ls="--")

    por_q = {r["q"]: r for r in registros}
    caixa_por_q = {q: caixa for q, _, caixa in quadros}

    # F1 — o que o contador enxerga
    fig, ax = plt.subplots(figsize=(7, 5.8))
    quadro_vazio(ax, "F1 · O quadro de 640×480, a caixa da pessoa 1 no quadro 522 e a linha A→B")
    xs = list(range(0, LARGURA + 1, 8))
    ys = list(range(0, ALTURA + 1, 8))
    dentro = [(x, y) for x in xs for y in ys if geometria.lado(A, B, (x, y)) == LADO_DENTRO]
    ax.scatter([p[0] for p in dentro], [p[1] for p in dentro], s=3, color=COR_DENTRO, alpha=0.15)
    ax.text(30, 472, "lado_dentro = +1: o lado da câmera, para onde a pessoa vem", color=COR_DENTRO, fontsize=8)
    x1, y1, x2, y2 = caixa_por_q[522]
    ax.add_patch(plt.Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False, color="black", lw=1.5))
    pe = geometria.ponto_base((x1, y1, x2, y2))
    ax.plot(*pe, "o", color=COR_PE, ms=8)
    ax.annotate(f"pé = {f(pe)}", pe, xytext=(10, -4), textcoords="offset points", color=COR_PE)
    ax.annotate(f"caixa [x1, y1, x2, y2] = [{x1}, {y1}, {x2}, {y2}]", (x1, y1), xytext=(0, 6), textcoords="offset points", fontsize=8)
    linha_ab(ax)
    fig.tight_layout()
    fig.savefig(FIGURAS / "f1.png")
    plt.close(fig)

    # F2 — campo de sinal
    fig, ax = plt.subplots(figsize=(7, 5.8))
    quadro_vazio(ax, "F2 · O sinal do produto vetorial em cada ponto do quadro")
    xs = list(range(4, LARGURA, 10))
    ys = list(range(4, ALTURA, 10))
    pts = [(x, y, geometria.lado(A, B, (x, y))) for x in xs for y in ys]
    for sinal, cor, rot in ((1, COR_DENTRO, "+1"), (-1, COR_FORA, "−1")):
        sel = [(x, y) for x, y, s in pts if s == sinal]
        ax.scatter([p[0] for p in sel], [p[1] for p in sel], s=6, color=cor, alpha=0.5, label=f"lado = {rot}")
    linha_ab(ax)
    reta_inteira(ax)
    ax.text(20, 395, "a reta continua além de A e de B: o sinal muda nela inteira", fontsize=8, color=COR_LINHA,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.85))
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIGURAS / "f2.png")
    plt.close(fig)

    # F3 — paralelogramo e zona morta
    fig, ax = plt.subplots(figsize=(7, 5.8))
    quadro_vazio(ax, "F3 · |produto vetorial| é a área do paralelogramo; dividida pela base dá a altura")
    P = por_q[522]["suavizado"]
    quarto = (P[0] + AB[0], P[1] + AB[1])
    ax.add_patch(Polygon([A, B, quarto, P], closed=True, color=COR_FORA, alpha=0.2))
    ax.plot([A[0], P[0]], [A[1], P[1]], color=COR_FORA, lw=1.5)
    ax.plot([B[0], quarto[0]], [B[1], quarto[1]], color=COR_FORA, lw=1.5, ls=":")
    ax.plot([P[0], quarto[0]], [P[1], quarto[1]], color=COR_FORA, lw=1.5, ls=":")
    ax.plot(*P, "o", color=COR_PE, ms=8)
    ax.annotate(f"P = pé no q522 = {f(P)}", P, xytext=(8, -6), textcoords="offset points", color=COR_PE)
    cross = geometria.produto_vetorial(A, B, P)
    d = geometria.distancia_ponto_reta(P, A, B)
    base = hypot(*AB)
    n = (-AB[1] / base, AB[0] / base)                       # normal unitária à reta
    sinal = 1 if cross > 0 else -1
    sope = (P[0] - n[0] * d * sinal, P[1] - n[1] * d * sinal)
    ax.plot([P[0], sope[0]], [P[1], sope[1]], color="black", lw=1, ls="--")
    ax.annotate(f"altura = d = {d:.1f} px", ((P[0] + sope[0]) / 2, (P[1] + sope[1]) / 2),
                xytext=(10, 0), textcoords="offset points")
    ax.text(60, 300, f"área = |cross| = {abs(cross):.0f} px²\nbase = |AB| = {base:.1f} px\n"
                     f"altura = {abs(cross):.0f} / {base:.1f} = {d:.1f} px", color=COR_FORA)
    faixa = 15
    dy = faixa / (AB[0] / base)
    ax.fill_between([0, LARGURA], [y_reta(0) - dy, y_reta(LARGURA) - dy], [y_reta(0) + dy, y_reta(LARGURA) + dy],
                    color=COR_LINHA, alpha=0.15)
    ax.text(8, 466, "zona morta: d < 15 px, ao longo da reta inteira", fontsize=8, color=COR_LINHA)
    linha_ab(ax)
    fig.tight_layout()
    fig.savefig(FIGURAS / "f3.png")
    plt.close(fig)

    # F4 — segmento vs reta (recorte da região da porta)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    quadro_vazio(ax, "F4 · Dois caminhos cruzam a reta; só um cruza o segmento AB (recorte: y de 380 a 480)")
    ax.set_xlim(180, 620)
    ax.set_ylim(ALTURA, 380)
    ax.set_aspect("auto")
    reta_inteira(ax)
    caminhos = [
        ("conta", por_q[534]["suavizado"], por_q[542]["suavizado"], COR_PE, (190, 456)),
        ("não conta", (500.0, 400.0), (500.0, 470.0), "purple", (510, 402)),
    ]
    for nome, p1, p2, cor, desl in caminhos:
        ax.annotate("", xy=p2, xytext=p1, arrowprops=dict(arrowstyle="->", color=cor, lw=2))
        o = (geometria.lado(p1, p2, A), geometria.lado(p1, p2, B), geometria.lado(A, B, p1), geometria.lado(A, B, p2))
        cruza = geometria.segmentos_se_cruzam(p1, p2, A, B)
        texto = (
            f"{nome}: {f(p1)} → {f(p2)}\n"
            f"o1 = {o[0]:+d}   o2 = {o[1]:+d}\n"
            f"o3 = {o[2]:+d}   o4 = {o[3]:+d}\n"
            f"cruza o segmento? {cruza}"
        )
        ax.text(desl[0], desl[1], texto, color=cor, fontsize=8, va="top")
    ax.text(520, 428, f"a reta em x = 500 está em y = {y_reta(500):.1f}", fontsize=8, color=COR_LINHA)
    linha_ab(ax)
    fig.tight_layout()
    fig.savefig(FIGURAS / "f4.png")
    plt.close(fig)

    # F5 — amostragem irregular e média móvel
    dts = [float(r["dt_ms"]) for r in csv.DictReader((AQUI / "intervalos_ms.csv").open(encoding="utf-8"))]
    dts_ord = sorted(dts)
    p50, p95 = median(dts), dts_ord[int(0.95 * len(dts_ord))]
    fps_medido = 1000 / (sum(dts) / len(dts))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4))
    ax1.hist([min(d, 400) for d in dts], bins=80, color=COR_DENTRO)
    ax1.axvline(p50, color="black", ls="--", label=f"mediana {p50:.0f} ms")
    ax1.axvline(p95, color=COR_FORA, ls="--", label=f"p95 {p95:.0f} ms")
    ax1.set_xlabel("intervalo entre quadros consecutivos (ms), cortado em 400")
    ax1.set_ylabel("quadros")
    ax1.set_title(f"F5a · A gravação inteira: {len(dts)} intervalos, máximo {max(dts) / 1000:.2f} s", fontsize=10)
    ax1.legend()
    sel = [r for r in registros if r["q"] <= 543]
    ts = [r["t"] for r in sel]
    ax2.plot(ts, [r["bruto"][1] for r in sel], "o-", color="gray", ms=4, label="y do pé, bruto")
    ax2.plot(ts, [r["suavizado"][1] for r in sel], "o-", color=COR_PE, ms=4, label="y do pé, média móvel de 3")
    ax2.axhline(y_reta(300), color=COR_LINHA, lw=1.5, label=f"a linha (y = {y_reta(300):.0f} em x = 300)")
    ax2.invert_yaxis()
    ax2.set_xlabel("tempo desde o quadro 520 (s)")
    ax2.set_ylabel("y (px) — cresce para baixo")
    ax2.set_title("F5b · Pessoa 1: o ponto suavizado chega ~1 quadro depois do bruto", fontsize=10)
    ax2.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(FIGURAS / "f5.png")
    plt.close(fig)

    # F6 — distância com sinal contra o quadro
    fig, ax = plt.subplots(figsize=(9, 4.8))
    sel = [r for r in registros if r["q"] <= 545]
    qs = [r["q"] for r in sel]
    ds = [r["cross"] / base for r in sel]
    ax.axhspan(-15, 15, color=COR_LINHA, alpha=0.12)
    ax.axhline(0, color=COR_LINHA, lw=1.5)
    ax.plot(qs, ds, "o-", color=COR_PE, ms=5)
    ax.text(520.3, 11, "zona morta: |d| < 15 px", color=COR_LINHA, fontsize=8)
    ax.axvspan(519.5, 521.5, color="gray", alpha=0.15)
    ax.text(520.5, -60, "idade < 3", fontsize=8, ha="center")
    ax.annotate("ENTRADA no q542\n(zona morta de 15 px)", (542, ds[qs.index(542)]), xytext=(-120, 10), textcoords="offset points",
                arrowprops=dict(arrowstyle="->"), fontsize=9)
    ax.annotate("com zona 0: q540", (540, ds[qs.index(540)]), xytext=(20, -60), textcoords="offset points",
                arrowprops=dict(arrowstyle="->"), fontsize=8)
    ax.annotate("com zona 30: q544\n(y2 já é a borda do quadro)", (544, ds[qs.index(544)]), xytext=(-40, 30), textcoords="offset points",
                arrowprops=dict(arrowstyle="->"), fontsize=8)
    ax.set_xlabel("quadro")
    ax.set_ylabel("distância com sinal à reta AB (px)\n− fora · + dentro")
    ax.set_title("F6 · O pé da pessoa 1 se aproxima, atravessa a faixa, e o evento sai no quadro 542", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURAS / "f6.png")
    plt.close(fig)

    return dict(p50=p50, p95=p95, max_s=max(dts) / 1000, fps=fps_medido, n=len(dts))


# -------------------------------------------------------------------- conferir

def conferir(quadros):
    """Roda o código de produção do Limiar sobre os mesmos casos e exige igualdade."""
    from datetime import timedelta

    # O pacote não é instalado (pyproject: package = false); vive em src/.
    sys.path.insert(0, str(AQUI.parents[1] / "src"))
    from fluxo.contagem import geometria as prod
    from fluxo.contagem.linha import LinhaDeContagem
    from fluxo.dominio.rastro import Rastro

    divergencias = 0
    comparacoes = 0
    # 1. as funções, nos casos de tests/test_geometria.py
    A_t, B_t = (450.0, 30.0), (450.0, 240.0)
    pontos = [(200.0, 100.0), (449.0, 100.0), (450.0, 100.0), (451.0, 100.0), (900.0, 100.0), (450.0, 1000.0)]
    for p in pontos:
        for nome, meu, deles in (
            ("lado", geometria.lado(A_t, B_t, p), prod.lado(A_t, B_t, p)),
            ("distancia_ponto_reta", geometria.distancia_ponto_reta(p, A_t, B_t), prod.distancia_ponto_reta(p, A_t, B_t)),
        ):
            comparacoes += 1
            if meu != deles:
                divergencias += 1
                print(f"DIVERGE {nome}{p}: aula {meu}, produção {deles}")
    caminhos = [
        ((300.0, 100.0), (600.0, 100.0)), ((300.0, 100.0), (440.0, 100.0)), ((300.0, 500.0), (600.0, 500.0)),
        ((300.0, 30.0), (600.0, 30.0)), ((300.0, 240.1), (600.0, 240.1)), ((450.0, 100.0), (450.0, 100.0)),
    ]
    for p1, p2 in caminhos:
        comparacoes += 1
        if geometria.segmentos_se_cruzam(p1, p2, A_t, B_t) != prod.segmentos_se_cruzam(p1, p2, A_t, B_t):
            divergencias += 1
            print(f"DIVERGE segmentos_se_cruzam{p1, p2}")
    # 2. a máquina de estados, na trilha real, com três zonas mortas
    t0 = datetime(2026, 9, 3, 14, 53, 26)
    for zona in (0.0, 15.0, 30.0):
        _, registros = rodar(quadros, zona_morta_px=zona)
        meus = [(r["q"], r["evento"]) for r in registros if r["evento"]]
        linha = LinhaDeContagem("aula", A, B, LADO_DENTRO, zona_morta_px=zona)
        deles = []
        for q, t, caixa in quadros:
            rastro = Rastro(id_local=1, caixa=caixa, confianca=0.9)
            for ev in linha.processar(q, t0 + timedelta(seconds=t), [rastro]):
                deles.append((q, ev.direcao.name))
        comparacoes += 1
        if meus != deles:
            divergencias += 1
            print(f"DIVERGE zona {zona}: aula {meus}, produção {deles}")
    if divergencias:
        print(f"{divergencias} divergência(s) em {comparacoes} comparações")
        sys.exit(1)
    print(f"OK: {comparacoes} comparações, nenhuma divergência entre a aula e o projeto.")


if __name__ == "__main__":
    quadros = carregar()
    if "--conferir" in sys.argv:
        conferir(quadros)
        sys.exit(0)

    c, registros = rodar(quadros)
    tabela(registros)
    print()
    for zona, esperado in ((15.0, 542), (0.0, 540), (30.0, 544)):
        c_z, _ = rodar(quadros, zona_morta_px=zona)
        print(f"zona morta {zona:>4} px -> eventos {c_z.eventos}")
        assert c_z.eventos == [(esperado, "ENTRADA")], (zona, c_z.eventos)
    stats = figuras(quadros, registros)
    print()
    print(f"amostragem: {stats['n']} intervalos, mediana {stats['p50']:.0f} ms, p95 {stats['p95']:.0f} ms, "
          f"máximo {stats['max_s']:.2f} s, {stats['fps']:.1f} quadros/s efetivos")
    print(f"figuras gravadas em {FIGURAS}")
