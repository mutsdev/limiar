"""Fila em disco para quando o serviço não responde.

A rede da portaria vai cair. Sem fila, evento perdido é contagem errada — e o
erro é silencioso, porque o número continua parecendo plausível.

Formato JSONL: uma linha por evento, append puro. Se o processo morrer no meio
da escrita, perde-se no máximo a última linha, e as anteriores continuam
legíveis. Um JSON único não teria essa propriedade.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from fluxo.dominio.evento import EventoCruzamento


class FilaLocal:
    def __init__(self, caminho: Path) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)

    def enfileirar(self, eventos: Iterable[EventoCruzamento]) -> int:
        n = 0
        with self.caminho.open("a", encoding="utf-8") as f:
            for evento in eventos:
                f.write(json.dumps(evento.model_dump(mode="json")) + "\n")
                n += 1
        return n

    def ler(self) -> list[EventoCruzamento]:
        if not self.caminho.exists():
            return []
        eventos = []
        for linha in self.caminho.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            try:
                eventos.append(EventoCruzamento.model_validate_json(linha))
            except ValueError:
                # Linha truncada por queda no meio da escrita. Descartar uma
                # linha é melhor que travar a fila inteira.
                continue
        return eventos

    def limpar(self) -> None:
        if self.caminho.exists():
            self.caminho.unlink()

    @property
    def tamanho(self) -> int:
        if not self.caminho.exists():
            return 0
        linhas = self.caminho.read_text(encoding="utf-8").splitlines()
        return sum(1 for linha in linhas if linha.strip())
