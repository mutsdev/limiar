"""O conjunto de ocupação: quem entrou e ainda não saiu.

É a ideia que torna a re-identificação viável (PROJETO.txt §12): a pergunta
não é "quem é esta pessoa entre todas do mundo", é "qual das pessoas que
estão dentro do prédio agora acabou de sair". Conjunto fechado, pequeno, e
que encolhe a cada saída.

Três regras que não se negociam:
  * saída é resolvida em LOTE (janela de segundos), pelo húngaro — nunca uma
    por vez;
  * nunca se força um par: sem candidato bom, a saída fica "não atribuída";
  * a identidade é do dia. Virou o dia, a galeria some inteira.

Nada aqui sabe o que é imagem. Entram assinaturas prontas, saem decisões.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fluxo.dominio.evento import Direcao, data_de_referencia
from fluxo.reid.assinatura import Assinatura, media, similaridade
from fluxo.reid.atribuicao import atribuir

METODO_NOVA = "nova"
METODO_REENTRADA = "reentrada"
METODO_SAIDA = "saida"
METODO_NAO_ATRIBUIDO = "nao_atribuido"
METODOS = (METODO_NOVA, METODO_REENTRADA, METODO_SAIDA, METODO_NAO_ATRIBUIDO)

# Etiqueta de quem saiu e ainda não foi resolvido pelo lote, ou ficou sem par.
SEM_PAR = "?"


@dataclass(slots=True)
class Pessoa:
    """Um pseudônimo do dia e as assinaturas vistas dele."""

    pseudonimo: str
    assinaturas: list[Assinatura]
    primeiro_visto: datetime
    ultimo_visto: datetime
    dentro: bool = True
    entradas: int = 0
    saidas: int = 0

    @property
    def assinatura(self) -> Assinatura:
        return media(self.assinaturas)

    def lembrar(self, assinatura: Assinatura, instante: datetime, memoria: int) -> None:
        # Guarda as últimas N: a roupa não muda no dia, mas a luz e o ângulo
        # mudam, e a média de várias passagens é mais estável que uma só.
        self.assinaturas.append(list(assinatura))
        del self.assinaturas[:-memoria]
        self.ultimo_visto = instante


@dataclass(frozen=True, slots=True)
class Decisao:
    """O que a galeria concluiu sobre um evento de cruzamento."""

    id_evento: str
    id_local: int
    direcao: Direcao
    instante: datetime
    pseudonimo: str | None
    similaridade: float | None
    metodo: str
    pessoa_nova: bool = False

    @property
    def atribuido(self) -> bool:
        return self.pseudonimo is not None


@dataclass(slots=True)
class _SaidaPendente:
    id_evento: str
    id_local: int
    assinatura: Assinatura
    instante: datetime


@dataclass
class Galeria:
    # Abaixo disto uma saída não é ninguém que está dentro.
    limiar_saida: float = 0.70
    # Entrada parecida com alguém que saiu hoje é a mesma pessoa voltando.
    limiar_reentrada: float = 0.75
    # Quanto tempo uma saída espera por companhia antes de o lote ser resolvido.
    janela_lote_s: float = 60.0
    # Quem está "dentro" há mais que isto é uma saída perdida, não uma pessoa.
    max_permanencia_h: float = 12.0
    # Assinaturas guardadas por pessoa.
    memoria: int = 5

    pessoas: dict[str, Pessoa] = field(default_factory=dict, init=False)
    data_ref: date | None = field(default=None, init=False)
    _pendentes: list[_SaidaPendente] = field(default_factory=list, init=False)
    _etiquetas: dict[int, str] = field(default_factory=dict, init=False)
    _proximo: int = field(default=1, init=False)

    # Contadores auditáveis. "Fantasma" é o número que diz se as saídas estão
    # sendo perdidas — e é o que contamina a atribuição se ninguém olhar.
    criadas: int = field(default=0, init=False)
    reentradas: int = field(default=0, init=False)
    atribuidas: int = field(default=0, init=False)
    nao_atribuidas: int = field(default=0, init=False)
    fantasmas: int = field(default=0, init=False)

    @classmethod
    def de_pipeline(cls, pipeline: dict) -> Galeria:
        r = pipeline.get("reid", {})
        return cls(
            limiar_saida=float(r.get("limiar_saida", 0.70)),
            limiar_reentrada=float(r.get("limiar_reentrada", 0.75)),
            janela_lote_s=float(r.get("janela_lote_s", 60)),
            max_permanencia_h=float(r.get("max_permanencia_h", 12)),
            memoria=int(r.get("memoria", 5)),
        )

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    @property
    def dentro(self) -> list[Pessoa]:
        return [p for p in self.pessoas.values() if p.dentro]

    @property
    def fora(self) -> list[Pessoa]:
        return [p for p in self.pessoas.values() if not p.dentro]

    @property
    def pendentes(self) -> int:
        return len(self._pendentes)

    def etiqueta(self, id_local: int) -> str | None:
        return self._etiquetas.get(id_local)

    def etiquetas(self) -> dict[int, str]:
        return dict(self._etiquetas)

    def esquecer(self, visiveis: set[int]) -> None:
        """Solta as etiquetas de tracks que sumiram, para o id reciclado não herdá-las."""
        for id_local in list(self._etiquetas):
            if id_local not in visiveis:
                del self._etiquetas[id_local]

    # ------------------------------------------------------------------
    # Ciclo por quadro
    # ------------------------------------------------------------------

    def preparar(self, instante: datetime) -> list[Decisao]:
        """Chame antes dos eventos de cada quadro: vira o dia e resolve lotes vencidos."""
        decisoes: list[Decisao] = []
        hoje = data_de_referencia(instante)
        if self.data_ref is not None and hoje != self.data_ref:
            # O dia acabou com saídas na fila: resolvem-se contra a galeria de
            # ontem, e só então ela some. Ninguém de ontem existe hoje.
            decisoes.extend(self.resolver(instante, forcar=True))
            self.pessoas.clear()
            self._etiquetas.clear()
            self._proximo = 1
        self.data_ref = hoje
        self.purgar_fantasmas(instante)
        decisoes.extend(self.resolver(instante))
        return decisoes

    def entrar(
        self, id_evento: str, id_local: int, assinatura: Assinatura, instante: datetime
    ) -> Decisao:
        """Alguém entrou: ou é quem saiu hoje voltando, ou é uma pessoa nova.

        Só quem está FORA é candidato. Comparar com quem está dentro casaria
        duas pessoas parecidas que estão no prédio ao mesmo tempo; uma saída
        perdida vira fragmentação, que o relatório mede — melhor que uma fusão,
        que ele não veria.
        """
        if self.data_ref is None:
            self.data_ref = data_de_referencia(instante)

        melhor: Pessoa | None = None
        melhor_sim = -1.0
        for p in self.fora:
            s = similaridade(assinatura, p.assinatura)
            if s > melhor_sim:
                melhor, melhor_sim = p, s

        if melhor is not None and melhor_sim >= self.limiar_reentrada:
            melhor.dentro = True
            melhor.entradas += 1
            melhor.lembrar(assinatura, instante, self.memoria)
            self.reentradas += 1
            self._etiquetas[id_local] = melhor.pseudonimo
            return Decisao(
                id_evento, id_local, Direcao.ENTRADA, instante,
                melhor.pseudonimo, melhor_sim, METODO_REENTRADA,
            )

        pessoa = Pessoa(
            pseudonimo=f"P{self._proximo}",
            assinaturas=[list(assinatura)],
            primeiro_visto=instante,
            ultimo_visto=instante,
            entradas=1,
        )
        self._proximo += 1
        self.pessoas[pessoa.pseudonimo] = pessoa
        self.criadas += 1
        self._etiquetas[id_local] = pessoa.pseudonimo
        return Decisao(
            id_evento, id_local, Direcao.ENTRADA, instante,
            pessoa.pseudonimo, None, METODO_NOVA, pessoa_nova=True,
        )

    def sair(
        self, id_evento: str, id_local: int, assinatura: Assinatura, instante: datetime
    ) -> None:
        """Alguém saiu. Entra na fila; a decisão é do lote.

        A etiqueta provisória ("P7?") é só para a tela — o vínculo gravado é o
        que `resolver` devolver.
        """
        if self.data_ref is None:
            self.data_ref = data_de_referencia(instante)
        self._pendentes.append(_SaidaPendente(id_evento, id_local, list(assinatura), instante))

        palpite = SEM_PAR
        melhor_sim = -1.0
        for p in self.dentro:
            s = similaridade(assinatura, p.assinatura)
            if s > melhor_sim:
                melhor_sim = s
                palpite = f"{p.pseudonimo}?" if s >= self.limiar_saida else SEM_PAR
        self._etiquetas[id_local] = palpite

    def resolver(self, instante: datetime, forcar: bool = False) -> list[Decisao]:
        """Resolve o lote de saídas se a janela venceu (ou se forçado).

        Em lote porque duas pessoas parecidas saindo juntas é o caso que a
        atribuição gulosa erra; o húngaro olha as duas ao mesmo tempo.
        """
        if not self._pendentes:
            return []
        mais_antiga = min(p.instante for p in self._pendentes)
        if not forcar and (instante - mais_antiga).total_seconds() < self.janela_lote_s:
            return []

        pendentes, self._pendentes = self._pendentes, []
        candidatas = self.dentro
        pares, sem_par = atribuir(
            [p.assinatura for p in pendentes],
            [c.assinatura for c in candidatas],
            self.limiar_saida,
        )

        decisoes: list[Decisao] = []
        for i, j, sim in pares:
            saida, pessoa = pendentes[i], candidatas[j]
            pessoa.dentro = False
            pessoa.saidas += 1
            pessoa.lembrar(saida.assinatura, saida.instante, self.memoria)
            self.atribuidas += 1
            self._etiquetas[saida.id_local] = pessoa.pseudonimo
            decisoes.append(Decisao(
                saida.id_evento, saida.id_local, Direcao.SAIDA, saida.instante,
                pessoa.pseudonimo, sim, METODO_SAIDA,
            ))
        for i in sem_par:
            saida = pendentes[i]
            self.nao_atribuidas += 1
            self._etiquetas[saida.id_local] = SEM_PAR
            decisoes.append(Decisao(
                saida.id_evento, saida.id_local, Direcao.SAIDA, saida.instante,
                None, None, METODO_NAO_ATRIBUIDO,
            ))
        decisoes.sort(key=lambda d: d.instante)
        return decisoes

    def purgar_fantasmas(self, instante: datetime) -> int:
        """Quem está "dentro" há tempo demais teve a saída perdida.

        Fica na galeria (pode voltar amanhã? não — some com o dia), mas sai do
        conjunto de candidatos: senão ele rouba o par de uma saída real.
        """
        limite = timedelta(hours=self.max_permanencia_h)
        n = 0
        for p in self.dentro:
            if instante - p.ultimo_visto > limite:
                p.dentro = False
                n += 1
        self.fantasmas += n
        return n

    def fechar(self, instante: datetime) -> list[Decisao]:
        """Fim da execução: o que está na fila é resolvido agora."""
        return self.resolver(instante, forcar=True)
