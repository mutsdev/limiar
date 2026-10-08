"""Extrai a trilha da pessoa 1 para ``pessoa1.csv``.

Lê ``dados/trilhas/entrada_real.jsonl`` (gravação real da entrada, 03/09/2026)
e guarda só as caixas do id 1, quadros 520 a 571: número do quadro, instante de
chegada do quadro, os quatro cantos da caixa e a confiança do detector.

Grava também ``intervalos_ms.csv``: o intervalo entre quadros consecutivos
da gravação inteira, em milissegundos, para o capítulo sobre amostragem.

Não há imagem nem identidade em nenhum ponto: são coordenadas em pixels e
instantes. Roda uma vez; os CSV resultantes vão junto com o material.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
TRILHA = AQUI.parents[1] / "dados" / "trilhas" / "entrada_real.jsonl"
SAIDA = AQUI / "pessoa1.csv"
INTERVALOS = AQUI / "intervalos_ms.csv"
PESSOA, DE, ATE = 1, 520, 571

linhas = []
instantes = []
for texto in TRILHA.read_text(encoding="utf-8").splitlines()[1:]:
    d = json.loads(texto)
    if "r" not in d:
        continue
    instantes.append(datetime.fromisoformat(d["t"]))
    if not (DE <= d["q"] <= ATE):
        continue
    for id_, x1, y1, x2, y2, conf in d["r"]:
        if id_ == PESSOA:
            linhas.append((d["q"], d["t"], x1, y1, x2, y2, conf))

with INTERVALOS.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["dt_ms"])
    for antes, depois in zip(instantes, instantes[1:]):
        w.writerow([round((depois - antes).total_seconds() * 1000, 1)])
print(f"{len(instantes) - 1} intervalos gravados em {INTERVALOS.name}")

with SAIDA.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["q", "t", "x1", "y1", "x2", "y2", "conf"])
    w.writerows(linhas)
print(f"{len(linhas)} quadros gravados em {SAIDA.name}")
