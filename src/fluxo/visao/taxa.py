"""Quantos quadros por segundo este processo está realmente fechando.

Não é o FPS da câmera nem o do arquivo: é o do laço inteiro — leitura, YOLO,
rastreio, contagem e desenho. É esse o número que diz se a contagem está
acompanhando a cena, e é ele que cai quando a máquina não dá conta.

Ao lado da latência, separa os dois motivos de uma degradação: latência
subindo com a taxa estável é CPU deste processo; as duas caindo juntas é a
rede ou a placa parando de entregar quadros.

O relógio é `time.monotonic`, e não o do calendário: ajuste de horário de
verão ou sincronização de NTP no meio da medição não produzem intervalo
negativo.

Só depende da biblioteca padrão — o placar importa cv2, este módulo não, e
assim ele continua testável no ambiente de núcleo.
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from collections.abc import Callable

# A mesma janela da latência, e pela mesma razão: pouco mais de um segundo de
# história a ~11 q/s. As duas leituras aparecem juntas no placar e reagem no
# mesmo ritmo, então uma queda comum às duas se lê de uma vez.
JANELA_PADRAO = 15


def formatar(quadros_por_s: float) -> str:
    """Texto do placar. ASCII puro — cv2.putText não desenha acento."""
    if quadros_por_s < 10.0:
        return f"{quadros_por_s:.1f} q/s"
    return f"{quadros_por_s:.0f} q/s"


class MedidorDeTaxa:
    """Mediana móvel do intervalo entre quadros, lida como quadros por segundo.

    Mede o intervalo e só então inverte, em vez de contar quadros numa janela
    de tempo: assim uma pausa longa não é diluída por quadros rápidos que
    vieram antes dela, e a mediana descarta o solavanco isolado da mesma forma
    que na latência.
    """

    def __init__(
        self,
        janela: int = JANELA_PADRAO,
        agora: Callable[[], float] | None = None,
    ) -> None:
        self._intervalos: deque[float] = deque(maxlen=max(1, janela))
        self._agora = agora or time.monotonic
        self._anterior: float | None = None

    def marcar(self) -> float | None:
        """Registra a passagem de um quadro.

        Devolve o intervalo desde o quadro anterior, em segundos, ou None no
        primeiro — que não tem antecessor e portanto não define intervalo
        nenhum.
        """
        agora = self._agora()
        intervalo = None
        if self._anterior is not None:
            intervalo = agora - self._anterior
            self._intervalos.append(intervalo)
        self._anterior = agora
        return intervalo

    @property
    def quadros_por_s(self) -> float | None:
        if not self._intervalos:
            return None
        mediana = statistics.median(self._intervalos)
        # Dois quadros no mesmo tique do relógio dariam divisão por zero. A
        # resolução do monotonic no Windows é ~15 ms, então isso acontece de
        # verdade em vídeo pequeno rodando sem espera.
        return 1.0 / mediana if mediana > 0 else None

    @property
    def texto(self) -> str:
        """Pedaço do placar, ou "" enquanto não houver intervalo medido."""
        taxa = self.quadros_por_s
        return formatar(taxa) if taxa is not None else ""
