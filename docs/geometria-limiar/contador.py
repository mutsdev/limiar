"""A máquina de estados que transforma posições em "entrou" ou "saiu".

Versão didática de ``LinhaDeContagem`` (``src/fluxo/contagem/linha.py``),
para uma pessoa só. Segue a mesma ordem de decisão do código de produção e
devolve, a cada quadro, tudo o que foi calculado, para que se possa
acompanhar a decisão passo a passo. Ficaram de fora a costura de rastro
quebrado e o esquecimento de tracks antigos, que não mudam a geometria.
"""

from collections import deque

import geometria
from geometria import Caixa, Ponto


class Contador:
    """Uma linha de A a B e os limiares da contagem.

    ``lado_dentro`` é o sinal do produto vetorial que corresponde ao interior
    do prédio, medido na calibração. Os demais parâmetros são os padrões de
    ``config/pipeline.yaml``.
    """

    def __init__(
        self,
        a: Ponto,
        b: Ponto,
        lado_dentro: int = 1,
        zona_morta_px: float = 15.0,
        janela: int = 3,
        idade_minima: int = 3,
        cooldown_s: float = 1.5,
    ) -> None:
        self.a, self.b = a, b
        self.lado_dentro = lado_dentro
        self.zona_morta_px = zona_morta_px
        self.janela = max(1, janela)
        self.idade_minima = idade_minima
        self.cooldown_s = cooldown_s

        self._pontos: deque[Ponto] = deque(maxlen=self.janela)
        self.idade = 0
        # A memória da histerese: o último lado visto FORA da zona morta, e
        # onde a pessoa estava quando esse lado foi confirmado.
        self.lado_confirmado: int | None = None
        self.ancora: Ponto | None = None
        self.contou_em: float | None = None
        self.eventos: list[tuple[int, str]] = []

    def suavizado(self) -> Ponto:
        """Média móvel das últimas posições (a janela tem ``janela`` quadros)."""
        n = len(self._pontos)
        return (
            sum(p[0] for p in self._pontos) / n,
            sum(p[1] for p in self._pontos) / n,
        )

    def passo(self, quadro: int, t: float, caixa: Caixa) -> dict:
        """Processa um quadro e devolve o que foi calculado nele.

        ``t`` é o instante do quadro em segundos. O dicionário devolvido tem
        o pé bruto e o suavizado, o produto vetorial (px²), a distância à
        reta (px), o lado, e o motivo da decisão tomada.
        """
        bruto = geometria.ponto_base(caixa)
        self._pontos.append(bruto)
        self.idade += 1
        ponto = self.suavizado()
        cross = geometria.produto_vetorial(self.a, self.b, ponto)
        d = geometria.distancia_ponto_reta(ponto, self.a, self.b)
        lado_atual = geometria.lado(self.a, self.b, ponto)

        registro = {
            "q": quadro,
            "t": t,
            "bruto": bruto,
            "suavizado": ponto,
            "cross": cross,
            "d": d,
            "lado": lado_atual,
            "idade": self.idade,
            "lado_confirmado": self.lado_confirmado,
            "ancora": self.ancora,
            "evento": None,
        }

        # 1. Track recém-nascido não decide: uma detecção de um quadro só
        #    não é uma pessoa, e uma posição só não é uma trajetória.
        if self.idade < self.idade_minima:
            registro["motivo"] = "idade<3"
            return registro

        # 2. Perto demais da reta para decidir. Adiar não perde o cruzamento:
        #    a pessoa vai sair da faixa por um lado ou pelo outro.
        if d < self.zona_morta_px:
            registro["motivo"] = "zona_morta"
            return registro

        # 3. Primeiro lado visto fora da faixa: só memoriza.
        if self.lado_confirmado is None:
            self.lado_confirmado, self.ancora = lado_atual, ponto
            registro["motivo"] = "confirma"
            return registro

        # 4. Mesmo lado de antes: só avança a âncora.
        if lado_atual == self.lado_confirmado:
            self.ancora = ponto
            registro["motivo"] = "mesmo_lado"
            return registro

        # 5. Trocou de lado. Conta se a corda da âncora até aqui atravessa o
        #    SEGMENTO desenhado, e se este track não acabou de contar.
        atravessou = geometria.segmentos_se_cruzam(self.ancora, ponto, self.a, self.b)
        em_cooldown = self.contou_em is not None and (t - self.contou_em) < self.cooldown_s
        if not atravessou:
            registro["motivo"] = "descartado_segmento"
        elif em_cooldown:
            registro["motivo"] = "descartado_cooldown"
        else:
            direcao = "ENTRADA" if lado_atual == self.lado_dentro else "SAIDA"
            self.contou_em = t
            self.eventos.append((quadro, direcao))
            registro["motivo"] = "evento"
            registro["evento"] = direcao

        # O lado é atualizado mesmo quando o evento é descartado; do contrário
        # o estado ficaria preso e o próximo cruzamento real se perderia.
        self.lado_confirmado, self.ancora = lado_atual, ponto
        return registro
