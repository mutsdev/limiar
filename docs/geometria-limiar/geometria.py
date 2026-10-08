"""A geometria da contagem, isolada para estudo.

Estas são as mesmas cinco funções que decidem, no Limiar, se uma pessoa
cruzou a linha da porta (``src/fluxo/contagem/geometria.py``). Aqui elas
aparecem sem nenhuma dependência: só ``math.hypot``. Um ponto é uma tupla
``(x, y)`` em pixels; uma caixa é ``(x1, y1, x2, y2)``.

Convenção de imagem: a origem fica no canto superior esquerdo, x cresce para
a direita e y cresce PARA BAIXO. Toda fórmula abaixo vale nesse sistema.
"""

from math import hypot

Ponto = tuple[float, float]
Caixa = tuple[float, float, float, float]

# Tolerância para tratar um float como zero. As coordenadas são pixels, então
# um valor abaixo disto é erro de arredondamento, não geometria. Não confundir
# com a zona morta (15 px), que é quem trata o ruído de medição.
EPS = 1e-9


def produto_vetorial(a: Ponto, b: Ponto, p: Ponto) -> float:
    """Componente z do produto vetorial (B − A) × (P − A), em px².

    Os dois vetores vivem no plano z = 0, então as componentes x e y do
    produto se anulam e sobra só a componente z:

        (bx − ax)·(py − ay) − (by − ay)·(px − ax)

    O sinal diz de que lado da reta AB o ponto P está. O módulo é a área do
    paralelogramo formado pelos dois vetores.
    """
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def lado(a: Ponto, b: Ponto, p: Ponto) -> int:
    """+1 ou −1 conforme o lado da reta AB em que P está; 0 se P está sobre ela.

    Qual sinal corresponde a "dentro do prédio" depende da ordem em que A e B
    foram clicados na calibração. Por isso o Limiar guarda ``lado_dentro``
    por câmera, medido, em vez de deduzi-lo.
    """
    v = produto_vetorial(a, b, p)
    if v > EPS:
        return 1
    if v < -EPS:
        return -1
    return 0


def distancia_ponto_reta(p: Ponto, a: Ponto, b: Ponto) -> float:
    """Distância perpendicular de P à RETA que passa por A e B, em px.

    Área do paralelogramo dividida pela base é a altura. Vale para a reta
    inteira: um ponto sobre o prolongamento de AB, além de B, tem distância
    zero. É esta função que define a zona morta.
    """
    comprimento = hypot(b[0] - a[0], b[1] - a[1])
    if comprimento < EPS:
        # A e B coincidem: não há reta, só um ponto.
        return hypot(p[0] - a[0], p[1] - a[1])
    return abs(produto_vetorial(a, b, p)) / comprimento


def _no_retangulo(p: Ponto, q: Ponto, r: Ponto) -> bool:
    """Q está dentro da caixa que envolve o segmento PR.

    Só é consultado quando os três pontos são colineares (produto vetorial
    zero), para saber se o ponto toca o segmento ou só a reta.
    """
    return (
        min(p[0], r[0]) - EPS <= q[0] <= max(p[0], r[0]) + EPS
        and min(p[1], r[1]) - EPS <= q[1] <= max(p[1], r[1]) + EPS
    )


def segmentos_se_cruzam(p1: Ponto, p2: Ponto, a: Ponto, b: Ponto) -> bool:
    """O deslocamento P1 → P2 cruza o SEGMENTO AB?

    Dois segmentos se cruzam quando cada um separa as pontas do outro: A e B
    ficam em lados opostos da reta P1P2, e P1 e P2 ficam em lados opostos da
    reta AB. São quatro testes de lado.

    A diferença entre segmento e reta infinita importa: alguém que passa ao
    lado da porta, fora da linha desenhada, cruza a reta que a contém, mas
    não deve ser contado.
    """
    o1 = lado(p1, p2, a)
    o2 = lado(p1, p2, b)
    o3 = lado(a, b, p1)
    o4 = lado(a, b, p2)

    if o1 != o2 and o3 != o4:
        return True

    # Casos colineares: algum ponto cai exatamente sobre o outro segmento.
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
    """O pé: centro da base da caixa, ((x1 + x2) / 2, y2).

    É o ponto da pessoa que está no chão, o mesmo plano em que a linha foi
    desenhada. O centro da caixa se move quando a pessoa levanta o braço ou
    é ocluída no topo; o pé não.
    """
    x1, _, x2, y2 = caixa
    return ((x1 + x2) / 2.0, y2)
