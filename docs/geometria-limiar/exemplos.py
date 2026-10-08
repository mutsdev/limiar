"""Os exemplos numéricos da apostila, prontos para rodar e alterar.

Cada bloco imprime a entrada e o resultado que a apostila cita. Os vetores
estão no topo: troque um número, rode de novo e veja o que muda.

    python exemplos.py
"""

from math import hypot

from contador import Contador
from geometria import (
    distancia_ponto_reta,
    lado,
    ponto_base,
    produto_vetorial,
    segmentos_se_cruzam,
)

# A linha da câmera da entrada, como está em config/cameras.yaml, e o lado
# que a calibração mediu como "dentro". Pixels de um quadro de 640 x 480.
A = (253.0, 447.0)
B = (458.0, 438.0)
LADO_DENTRO = 1

# Pontos usados nos exemplos: pé suavizado da pessoa 1 em alguns quadros.
P_522 = (349.5, 370.5)   # longe da linha, ainda do lado de fora
P_540 = (302.2, 445.6)   # em cima da linha
P_542 = (298.0, 467.6)   # já do lado de dentro


def titulo(s: str) -> None:
    print(f"\n{'=' * 60}\n{s}\n{'=' * 60}")


# ---------------------------------------------------------------- capítulo 1
titulo("1. O pé da caixa")
caixa = (331.9, 205.0, 374.4, 370.4)   # pessoa 1, quadro 520
print(f"caixa {caixa}")
print(f"pé = ((x1 + x2) / 2, y2) = {ponto_base(caixa)}")

# ---------------------------------------------------------------- capítulo 2
titulo("2. A linha é um vetor")
ab = (B[0] - A[0], B[1] - A[1])
print(f"A = {A}, B = {B}")
print(f"AB = B - A = {ab}")
print(f"|AB| = hypot{ab} = {hypot(*ab):.1f} px")

# ---------------------------------------------------------------- capítulo 3
titulo("3. De que lado?")
for nome, p in (("q522", P_522), ("q540", P_540), ("q542", P_542)):
    v = produto_vetorial(A, B, p)
    print(f"{nome}  P = {p}  cross = {v:+.0f} px²  lado = {lado(A, B, p):+d}")
sobre = (355.5, 442.5)   # ponto exatamente sobre a reta (meio de AB)
print(f"meio  P = {sobre}  cross = {produto_vetorial(A, B, sobre):+.0f} px²  lado = {lado(A, B, sobre):+d}")
print()
print("Trocando a ordem de A e B o sinal inverte:")
print(f"  lado(A, B, q542) = {lado(A, B, P_542):+d}    lado(B, A, q542) = {lado(B, A, P_542):+d}")

# ---------------------------------------------------------------- capítulo 4
titulo("4. A que distância?")
for nome, p in (("q522", P_522), ("q540", P_540)):
    v = produto_vetorial(A, B, p)
    d = distancia_ponto_reta(p, A, B)
    dentro_da_faixa = "dentro da zona morta" if d < 15 else "fora da zona morta"
    print(f"{nome}  |cross| / |AB| = {abs(v):.0f} / {hypot(*ab):.1f} = {d:.1f} px  ({dentro_da_faixa})")
alem_de_b = (600.0, 431.8)   # sobre o prolongamento da reta, além de B
print(f"além de B  P = {alem_de_b}  d = {distancia_ponto_reta(alem_de_b, A, B):.2f} px  (a distância é à reta, não ao segmento)")

# ---------------------------------------------------------------- capítulo 5
titulo("5. Segmento, não reta")
casos = [
    ("passa pela porta ", (313.0, 423.9), (298.0, 467.6)),   # âncora do q534 até o pé do q542
    ("passa ao lado    ", (500.0, 400.0), (500.0, 470.0)),   # cruza a reta à direita de B
]
for nome, p1, p2 in casos:
    o1, o2 = lado(p1, p2, A), lado(p1, p2, B)
    o3, o4 = lado(A, B, p1), lado(A, B, p2)
    print(f"{nome} {p1} -> {p2}")
    print(f"    o1 = lado(P1,P2,A) = {o1:+d}   o2 = lado(P1,P2,B) = {o2:+d}   o3 = lado(A,B,P1) = {o3:+d}   o4 = lado(A,B,P2) = {o4:+d}")
    print(f"    cruza o segmento? {segmentos_se_cruzam(p1, p2, A, B)}")
y_reta_500 = A[1] + (B[1] - A[1]) * (500 - A[0]) / (B[0] - A[0])
print(f"(em x = 500 a reta está em y = {y_reta_500:.1f}: o segundo caminho cruza a RETA, mas não o segmento)")

# ---------------------------------------------------------------- capítulo 6
titulo("6. Média móvel de 3 quadros")
pes = [(302.0, 443.7), (299.8, 457.8), (298.2, 467.7)]   # pés brutos q539, q540, q541
media = (sum(p[0] for p in pes) / 3, sum(p[1] for p in pes) / 3)
print(f"pés brutos {pes}")
print(f"média = ({media[0]:.1f}, {media[1]:.1f})  -> o ponto suavizado do q541 fica ~1 quadro atrás do bruto")

# ---------------------------------------------------------------- capítulo 7
titulo("7. A máquina de estados numa trajetória inventada")
# Seis pés, um por quadro, a cada 0,1 s: a pessoa desce e cruza a porta.
trajetoria = [
    (520, 0.0, (330.0, 200.0, 370.0, 380.0)),
    (521, 0.1, (328.0, 200.0, 368.0, 400.0)),
    (522, 0.2, (326.0, 200.0, 366.0, 420.0)),
    (523, 0.3, (324.0, 200.0, 364.0, 440.0)),
    (524, 0.4, (322.0, 200.0, 362.0, 460.0)),
    (525, 0.5, (320.0, 200.0, 360.0, 480.0)),
]
c = Contador(A, B, LADO_DENTRO)
print(f"{'q':>4} {'pé suavizado':>16} {'cross':>8} {'d':>6} {'lado':>4}  motivo")
for q, t, caixa in trajetoria:
    r = c.passo(q, t, caixa)
    s = f"({r['suavizado'][0]:.1f}, {r['suavizado'][1]:.1f})"
    print(f"{q:>4} {s:>16} {r['cross']:>+8.0f} {r['d']:>6.1f} {r['lado']:>+4d}  {r['motivo']}" + (f" -> {r['evento']}" if r["evento"] else ""))
print(f"eventos: {c.eventos}")

# ---------------------------------------------------------------- capítulo 9
titulo("9. Cooldown: a mesma pessoa cruzando três vezes")
# Pés já suavizados não importam aqui; o que importa são os instantes.
# Entra em t = 0, volta em t = 1,08 s, entra de novo em t = 2,08 s.
def cruzamentos(instantes):
    c = Contador(A, B, LADO_DENTRO, janela=1, idade_minima=1)
    q = 0
    for t_cruza, sentido in instantes:
        # dois quadros de um lado, dois do outro, com o cruzamento em t_cruza
        y_antes, y_depois = (400.0, 475.0) if sentido == "desce" else (475.0, 400.0)
        for dt, y in ((-0.2, y_antes), (-0.1, y_antes), (0.0, y_depois), (0.1, y_depois)):
            q += 1
            c.passo(q, t_cruza + dt, (300.0, 200.0, 340.0, y))
    return c.eventos

print("entra 0,00 / volta 1,08 / entra 2,08 s:", cruzamentos([(0.0, "desce"), (1.08, "sobe"), (2.08, "desce")]))
print("entra 0,00 / volta 1,58 / entra 2,58 s:", cruzamentos([(0.0, "desce"), (1.58, "sobe"), (2.58, "desce")]))
print("entra 0,00 / volta 1,58 / entra 3,16 s:", cruzamentos([(0.0, "desce"), (1.58, "sobe"), (3.16, "desce")]))
