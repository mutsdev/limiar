"""Entrega dos eventos ao serviço central.

Reenvio é seguro por construção: cada evento carrega uma chave determinística,
e o serviço reconhece a repetição. Isso é o que permite tentar de novo sem
medo de inflar a contagem.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from fluxo.agente.fila_local import FilaLocal
from fluxo.dominio.evento import EventoCruzamento


@dataclass
class Remetente:
    url: str
    fila: FilaLocal
    timeout: float = 5.0
    tentativas: int = 3
    espera_inicial: float = 0.5

    enviados: int = field(default=0, init=False)
    enfileirados: int = field(default=0, init=False)

    def _postar(self, eventos: list[EventoCruzamento]) -> bool:
        corpo = [e.model_dump(mode="json") for e in eventos]
        espera = self.espera_inicial
        for tentativa in range(1, self.tentativas + 1):
            try:
                r = httpx.post(
                    f"{self.url}/eventos/lote", json=corpo, timeout=self.timeout
                )
                r.raise_for_status()
                return True
            except (httpx.HTTPError, httpx.TimeoutException):
                if tentativa == self.tentativas:
                    return False
                time.sleep(espera)
                espera *= 2  # recuo exponencial: rede caída não melhora insistindo
        return False

    def enviar(self, eventos: list[EventoCruzamento]) -> bool:
        """Tenta enviar. O que não for aceito vai para a fila, não se perde."""
        if not eventos:
            return True
        if self._postar(eventos):
            self.enviados += len(eventos)
            return True
        self.enfileirados += self.fila.enfileirar(eventos)
        return False

    def drenar_fila(self) -> int:
        """Reenvia o que ficou acumulado. Devolve quantos saíram."""
        pendentes = self.fila.ler()
        if not pendentes:
            return 0
        if self._postar(pendentes):
            self.fila.limpar()
            self.enviados += len(pendentes)
            return len(pendentes)
        return 0

    def servico_no_ar(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/saude", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False
