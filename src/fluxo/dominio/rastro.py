"""Uma pessoa sendo acompanhada pelo rastreador.

Vive no domínio, e não em `visao`, porque a camada de contagem precisa dele e
não pode depender da camada de visão — a dependência só aponta para baixo.
"""

from __future__ import annotations

from dataclasses import dataclass

Ponto = tuple[float, float]
Caixa = tuple[float, float, float, float]  # x1, y1, x2, y2


@dataclass(frozen=True, slots=True)
class Rastro:
    """Uma detecção já associada a uma identidade local pelo rastreador.

    `id_local` vale só dentro desta câmera e enquanto a pessoa está visível.
    Se ela sair do quadro e voltar, ganha um número novo — e isso é esperado.
    """

    id_local: int
    caixa: Caixa
    confianca: float

    @property
    def ponto_base(self) -> Ponto:
        """Centro da base da caixa: onde a pessoa toca o chão.

        O centro da caixa oscila quando a pessoa levanta o braço ou é ocluída
        no topo. O ponto do pé fica no mesmo plano em que a linha de contagem
        foi desenhada, então a geometria corresponde à realidade física.
        """
        x1, _, x2, y2 = self.caixa
        return ((x1 + x2) / 2.0, y2)
