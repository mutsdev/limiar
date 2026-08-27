"""A linha virtual de contagem.

Recebe os rastros de cada quadro e emite eventos de cruzamento. Não conhece
vídeo, modelo nem rede: recebe posições e instantes, devolve eventos. É isso
que permite testá-la com trajetórias inventadas, sem nada pesado por perto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fluxo.contagem import geometria
from fluxo.contagem.trajetoria import Trajetoria
from fluxo.dominio.evento import Direcao, EventoCruzamento, Origem
from fluxo.dominio.rastro import Ponto, Rastro


@dataclass(slots=True)
class _EstadoTrack:
    trajetoria: Trajetoria
    # Último lado em que a pessoa esteve *fora* da zona morta. É o que torna a
    # histerese possível: dentro da faixa morta nada é confirmado.
    lado_confirmado: int | None = None
    # Onde ela estava quando esse lado foi confirmado. Serve para checar se o
    # deslocamento até a posição atual atravessa o segmento, e não só a reta.
    ancora: Ponto | None = None
    contou_em: datetime | None = None


@dataclass(slots=True)
class LinhaDeContagem:
    """Uma linha por câmera.

    `lado_dentro` é o sinal do produto vetorial que corresponde ao interior do
    prédio. Depende de como a câmera foi montada, e sai da calibração.
    """

    camera_id: str
    a: Ponto
    b: Ponto
    lado_dentro: int = 1
    idade_minima_track: int = 3
    janela_suavizacao: int = 3
    zona_morta_px: float = 15.0
    cooldown_segundos: float = 1.5
    quadros_ate_esquecer: int = 60
    # Costura de rastro quebrado. O rastreador encerra o track quando a pessoa
    # é ocluída e abre outro com id novo do outro lado do oclusor; sem costurar,
    # isso perde a travessia (o track novo nasce sem lado confirmado) ou a conta
    # duas vezes (o cooldown do track antigo foi embora com ele).
    #
    # Nasce DESLIGADA: nas sequências medidas até aqui ela não melhora o número
    # (docs/resultados.md §2). O padrão acompanha a medição, e não a intenção do
    # mecanismo. `scripts/reprocessar.py --varredura` decide isso por câmera.
    costura_quadros: int = 0
    costura_raio_px: float = 80.0
    origem: Origem = Origem.VISAO

    _estados: dict[int, _EstadoTrack] = field(default_factory=dict, init=False)
    entradas: int = field(default=0, init=False)
    saidas: int = field(default=0, init=False)
    costuras: int = field(default=0, init=False)

    def processar(
        self, quadro: int, instante: datetime, rastros: list[Rastro]
    ) -> list[EventoCruzamento]:
        """Atualiza o estado com os rastros do quadro e devolve o que cruzou."""
        eventos: list[EventoCruzamento] = []

        # Quem está no quadro agora não pode ser adotado por outro id: o track
        # continua vivo, e roubar o estado dele criaria dois erros de uma vez.
        presentes = {r.id_local for r in rastros}

        for rastro in rastros:
            evento = self._processar_rastro(quadro, instante, rastro, presentes)
            if evento is not None:
                eventos.append(evento)

        self._esquecer_antigos(quadro)
        return eventos

    def _adotar(
        self, rastro: Rastro, quadro: int, presentes: set[int]
    ) -> _EstadoTrack | None:
        """Procura o track recém-morto que este id novo continua.

        Três condições, e nenhuma delas é opcional: a lacuna precisa ser curta,
        o reaparecimento precisa ser perto, e cada órfão só pode ser adotado uma
        vez. Sem a terceira, uma pessoa parada perto da linha adotaria o mesmo
        estado várias vezes; sem as duas primeiras, duas pessoas diferentes que
        se cruzam viram uma só.
        """
        if self.costura_quadros <= 0:
            return None

        nascimento = rastro.ponto_base
        melhor_id, melhor_distancia = None, self.costura_raio_px
        for tid, estado in self._estados.items():
            if tid in presentes:
                continue
            lacuna = quadro - estado.trajetoria.ultimo_quadro
            if lacuna <= 0 or lacuna > self.costura_quadros:
                continue
            d = geometria.distancia(estado.trajetoria.suavizado(), nascimento)
            if d <= melhor_distancia:
                melhor_id, melhor_distancia = tid, d

        if melhor_id is None:
            return None

        # Sai do dicionário sob o id antigo e entra sob o novo: é isso que torna
        # a adoção um-para-um, sem precisar de uma marca separada.
        self.costuras += 1
        return self._estados.pop(melhor_id)

    def _processar_rastro(
        self, quadro: int, instante: datetime, rastro: Rastro, presentes: set[int]
    ) -> EventoCruzamento | None:
        estado = self._estados.get(rastro.id_local)
        if estado is None:
            # Herda trajetória, lado confirmado, âncora e o instante da última
            # contagem. Os dois primeiros recuperam a travessia partida no meio;
            # o último mantém o cooldown de pé e mata a contagem dupla.
            estado = self._adotar(rastro, quadro, presentes) or _EstadoTrack(
                Trajetoria(self.janela_suavizacao)
            )
            self._estados[rastro.id_local] = estado

        estado.trajetoria.adicionar(rastro.ponto_base, quadro)

        # Track recém-nascido não conta: elimina detecção de um quadro só, e
        # evita decidir com base numa única posição.
        if estado.trajetoria.quadros < self.idade_minima_track:
            return None

        ponto = estado.trajetoria.suavizado()

        # Perto demais da linha para decidir. Adiar não perde o cruzamento —
        # a pessoa vai sair da faixa de um lado ou do outro.
        if geometria.distancia_ponto_reta(ponto, self.a, self.b) < self.zona_morta_px:
            return None

        lado_atual = geometria.lado(self.a, self.b, ponto)

        if estado.lado_confirmado is None:
            estado.lado_confirmado = lado_atual
            estado.ancora = ponto
            return None

        if lado_atual == estado.lado_confirmado:
            estado.ancora = ponto
            return None

        # Trocou de lado. Só conta se o caminho até aqui atravessou o segmento
        # desenhado, e se o track não acabou de contar.
        evento = None
        atravessou = estado.ancora is not None and geometria.segmentos_se_cruzam(
            estado.ancora, ponto, self.a, self.b
        )
        if atravessou and not self._em_cooldown(estado, instante):
            direcao = (
                Direcao.ENTRADA if lado_atual == self.lado_dentro else Direcao.SAIDA
            )
            evento = EventoCruzamento.criar(
                self.camera_id,
                instante,
                direcao,
                track_id_local=rastro.id_local,
                confianca=rastro.confianca,
                origem=self.origem,
            )
            estado.contou_em = instante
            if direcao is Direcao.ENTRADA:
                self.entradas += 1
            else:
                self.saidas += 1

        # O lado é atualizado mesmo quando o evento é descartado; do contrário
        # o estado ficaria preso e o próximo cruzamento real se perderia.
        estado.lado_confirmado = lado_atual
        estado.ancora = ponto
        return evento

    def _em_cooldown(self, estado: _EstadoTrack, instante: datetime) -> bool:
        if estado.contou_em is None:
            return False
        return (instante - estado.contou_em).total_seconds() < self.cooldown_segundos

    def _esquecer_antigos(self, quadro: int) -> None:
        # Um estado esquecido cedo demais deixa de estar disponível para
        # adoção, e a costura para de funcionar sem dizer por quê.
        limite = max(self.quadros_ate_esquecer, self.costura_quadros)
        mortos = [
            tid
            for tid, e in self._estados.items()
            if quadro - e.trajetoria.ultimo_quadro > limite
        ]
        for tid in mortos:
            del self._estados[tid]

    @property
    def rastros_ativos(self) -> int:
        return len(self._estados)

    @classmethod
    def de_config(
        cls, camera_id: str, camera: dict, pipeline: dict, origem: Origem = Origem.VISAO
    ) -> LinhaDeContagem:
        """Monta a linha a partir de config/cameras.yaml + config/pipeline.yaml."""
        linha = camera.get("linha")
        if not linha or len(linha) != 4:
            raise ValueError(
                f"Câmera '{camera_id}' não tem linha calibrada. "
                f"Rode: python scripts/calibrar_linha.py --camera {camera_id}"
            )
        c = pipeline.get("contagem", {})
        return cls(
            camera_id=camera_id,
            a=(float(linha[0]), float(linha[1])),
            b=(float(linha[2]), float(linha[3])),
            lado_dentro=int(camera.get("lado_dentro", 1)),
            idade_minima_track=int(c.get("idade_minima_track", 3)),
            janela_suavizacao=int(c.get("janela_suavizacao", 3)),
            zona_morta_px=float(c.get("zona_morta_px", 15)),
            cooldown_segundos=float(c.get("cooldown_segundos", 1.5)),
            quadros_ate_esquecer=int(c.get("quadros_ate_esquecer", 60)),
            costura_quadros=int(c.get("costura_quadros", 0)),
            costura_raio_px=float(c.get("costura_raio_px", 80)),
            origem=origem,
        )
