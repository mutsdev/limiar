"""Quanto tempo o quadro que está na tela levou para chegar até ela.

O que este número mede: o intervalo entre o instante em que o JPEG terminou
de chegar da câmera e o instante em que ele foi desenhado — ou seja, a espera
na fila da `FonteViva` mais a inferência do YOLO. As duas pontas são lidas do
relógio DESTA máquina, então não há defasagem de relógio possível e o valor
nunca é negativo.

O que ele NÃO mede: exposição do sensor, compressão JPEG na placa e travessia
do wifi. O MJPEG do ESP32 não carrega instante de captura, e sem isso o atraso
antes da chegada é inobservável daqui. Por isso "aparente": é o pedaço do
atraso que este processo consegue enxergar, e o piso real é maior.

Serve para responder "o que estou vendo é agora?" — e, na operação, para
separar câmera lenta de máquina lenta: latência subindo com a taxa de quadros
estável é CPU; as duas caindo juntas é a rede ou a placa.

Só depende da biblioteca padrão: o placar importa cv2, este módulo não, e
assim ele continua testável no ambiente de núcleo.
"""

from __future__ import annotations

import statistics
from collections import deque
from collections.abc import Callable
from datetime import datetime

from fluxo.dominio.evento import FUSO_LOCAL

# Quantas amostras entram na mediana. A ~11 q/s isto é pouco mais de um
# segundo de história: curto o bastante para reagir a uma degradação, longo o
# bastante para o número não tremer a cada quadro.
JANELA_PADRAO = 15


def formatar(segundos: float) -> str:
    """Texto do placar. ASCII puro — cv2.putText não desenha acento."""
    if segundos < 10.0:
        return f"{segundos * 1000:.0f} ms"
    return f"{segundos:.1f} s"


class MedidorDeLatencia:
    """Mediana móvel do atraso aparente.

    A mediana, e não a média, porque uma pausa do coletor de lixo ou uma
    reconexão produz uma amostra ordens de grandeza maior que as vizinhas — e
    a média a carregaria por quinze quadros, fazendo parecer degradação
    contínua o que foi um solavanco. O preço é que o solavanco isolado não
    aparece no placar: quem precisa dele lê `mediana_s` quadro a quadro, ou o
    valor cru que `observar` devolve.
    """

    def __init__(
        self,
        janela: int = JANELA_PADRAO,
        agora: Callable[[], datetime] | None = None,
    ) -> None:
        self._amostras: deque[float] = deque(maxlen=max(1, janela))
        self._agora = agora or (lambda: datetime.now(FUSO_LOCAL))

    def observar(self, instante: datetime) -> float:
        """Registra o atraso deste quadro e devolve o valor cru, em segundos."""
        atraso = (self._agora() - instante).total_seconds()
        # Um quadro não pode chegar do futuro. Se chegou, o instante veio de
        # uma fonte que não é ao vivo (arquivo, datado pelo FPS) e a leitura
        # não significa nada — zerar é melhor que exibir número negativo.
        atraso = max(0.0, atraso)
        self._amostras.append(atraso)
        return atraso

    @property
    def mediana_s(self) -> float | None:
        return statistics.median(self._amostras) if self._amostras else None

    @property
    def texto(self) -> str:
        """Pedaço do placar, ou "" enquanto não houver amostra."""
        if not self._amostras:
            return ""
        return f"latencia {formatar(self.mediana_s)}"
