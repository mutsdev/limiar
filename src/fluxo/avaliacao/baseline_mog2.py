"""Linha de base: contagem por subtração de fundo.

Existe para dar um número contra o qual comparar o YOLO. Sem ela, "escolhi
YOLO" é afirmação; com ela, é resultado.

O detector é o UNICO componente trocado — linha, histerese, cooldown e direção
continuam os mesmos. Isolar a variável é o que torna a comparação justa; se o
pipeline inteiro mudasse, a diferença não teria explicação única.

Limitações conhecidas, e são o ponto: sombra vira pessoa, mudança de luz vira
movimento, e um grupo encostado vira um blob só — que conta como um.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from fluxo.dominio.rastro import Rastro


@dataclass
class ConfigFundo:
    historico: int = 300
    limiar_variancia: float = 24.0
    area_minima: int = 900          # px2; abaixo disso é ruído, não pessoa
    area_maxima: int = 120_000
    razao_min: float = 0.8          # altura/largura: pessoa em pé é mais alta
    distancia_maxima: float = 90.0  # px entre quadros para manter o mesmo id
    quadros_ate_perder: int = 12


@dataclass
class _Alvo:
    id_local: int
    centro: tuple[float, float]
    caixa: tuple[float, float, float, float]
    visto_em: int


@dataclass
class DetectorFundo:
    """MOG2 mais rastreio por vizinho mais próximo.

    O rastreador é deliberadamente ingênuo: é o que se consegue sem rede
    neural, e faz parte do que a comparação está medindo.
    """

    config: ConfigFundo = field(default_factory=ConfigFundo)

    def __post_init__(self) -> None:
        self._fundo = cv2.createBackgroundSubtractorMOG2(
            history=self.config.historico,
            varThreshold=self.config.limiar_variancia,
            detectShadows=True,
        )
        self._alvos: list[_Alvo] = []
        self._proximo_id = 1
        self._quadro = 0
        self._nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def atualizar(self, imagem) -> list[Rastro]:
        self._quadro += 1
        mascara = self._fundo.apply(imagem)

        # 127 é a marca de sombra do MOG2. Mantê-la dobraria a área de cada
        # pessoa e juntaria vizinhos num blob só.
        _, mascara = cv2.threshold(mascara, 200, 255, cv2.THRESH_BINARY)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, self._nucleo, iterations=2)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, self._nucleo, iterations=3)

        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidatos = []
        for c in contornos:
            area = cv2.contourArea(c)
            if not (self.config.area_minima <= area <= self.config.area_maxima):
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w == 0 or h / w < self.config.razao_min:
                continue
            centro = (x + w / 2.0, y + h / 2.0)
            caixa = (float(x), float(y), float(x + w), float(y + h))
            candidatos.append((centro, caixa))

        return self._associar(candidatos)

    def _associar(self, candidatos) -> list[Rastro]:
        livres = list(self._alvos)
        rastros: list[Rastro] = []

        for centro, caixa in candidatos:
            melhor, menor = None, self.config.distancia_maxima
            for alvo in livres:
                d = float(np.hypot(centro[0] - alvo.centro[0], centro[1] - alvo.centro[1]))
                if d < menor:
                    melhor, menor = alvo, d

            if melhor is None:
                melhor = _Alvo(self._proximo_id, centro, caixa, self._quadro)
                self._proximo_id += 1
                self._alvos.append(melhor)
            else:
                livres.remove(melhor)
                melhor.centro, melhor.caixa = centro, caixa
            melhor.visto_em = self._quadro

            # Confiança fixa: a subtração de fundo não produz uma. Inventar um
            # valor por detecção seria pior que assumir esta constante.
            rastros.append(Rastro(id_local=melhor.id_local, caixa=caixa, confianca=0.5))

        self._alvos = [
            a for a in self._alvos
            if self._quadro - a.visto_em <= self.config.quadros_ate_perder
        ]
        return rastros

    @property
    def dispositivo(self) -> str:
        return "cpu"
