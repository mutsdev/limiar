"""Quanto o re-ID acerta — medido contra um gabarito preenchido à mão.

O gabarito diz, para cada travessia, quem realmente era (um apelido). Daí
saem as três perguntas que importam:

  * PUREZA: dentro de um pseudônimo, que fração das travessias é da mesma
    pessoa? Cai quando o sistema CONFUNDE duas pessoas num P só.
  * FRAGMENTAÇÃO: uma pessoa real virou quantos pseudônimos? Sobe quando o
    sistema DIVIDE uma pessoa em vários P.
  * NÃO ATRIBUÍDO: que fração das saídas ficou sem par. É a parcela honesta,
    e precisa aparecer no relatório (PROJETO §12).

E, sem gabarito nenhum, a PERMANÊNCIA: quanto tempo cada P ficou dentro.

Python puro. As entradas são registros simples — o chamador os monta a partir
do banco, do índice de miniaturas ou das decisões de um replay.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from fluxo.dominio.evento import Direcao


@dataclass(frozen=True, slots=True)
class Registro:
    """Uma travessia já decidida: quem o sistema disse que era."""

    id_evento: str
    instante: datetime
    direcao: Direcao
    pseudonimo: str | None  # None = não atribuído

    @property
    def atribuido(self) -> bool:
        return self.pseudonimo is not None


@dataclass(slots=True)
class Pureza:
    # pseudonimo -> (apelido majoritário, travessias rotuladas, quantas são dele)
    por_pseudonimo: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    total: int = 0
    certos: int = 0

    @property
    def taxa(self) -> float:
        return self.certos / self.total if self.total else 0.0

    @property
    def confusoes(self) -> int:
        return self.total - self.certos


@dataclass(slots=True)
class Fragmentacao:
    # apelido -> pseudônimos em que apareceu
    por_apelido: dict[str, set[str]] = field(default_factory=dict)

    @property
    def pessoas(self) -> int:
        return len(self.por_apelido)

    @property
    def media(self) -> float:
        if not self.por_apelido:
            return 0.0
        return sum(len(ps) for ps in self.por_apelido.values()) / len(self.por_apelido)

    @property
    def divididas(self) -> int:
        return sum(1 for ps in self.por_apelido.values() if len(ps) > 1)


@dataclass(frozen=True, slots=True)
class Permanencia:
    pseudonimo: str
    entrada: datetime
    saida: datetime

    @property
    def segundos(self) -> float:
        return (self.saida - self.entrada).total_seconds()


def _rotulados(registros, gabarito: dict[str, str]):
    """Só o que tem pseudônimo E apelido no gabarito conta para pureza/fragmentação."""
    for r in registros:
        apelido = (gabarito.get(r.id_evento) or "").strip()
        if r.pseudonimo is not None and apelido:
            yield r, apelido


def pureza(registros: list[Registro], gabarito: dict[str, str]) -> Pureza:
    contagens: dict[str, Counter] = defaultdict(Counter)
    for r, apelido in _rotulados(registros, gabarito):
        contagens[r.pseudonimo][apelido] += 1

    resultado = Pureza()
    for pseudonimo, c in sorted(contagens.items()):
        apelido, n_dele = c.most_common(1)[0]
        n = sum(c.values())
        resultado.por_pseudonimo[pseudonimo] = (apelido, n, n_dele)
        resultado.total += n
        resultado.certos += n_dele
    return resultado


def fragmentacao(registros: list[Registro], gabarito: dict[str, str]) -> Fragmentacao:
    resultado = Fragmentacao()
    for r, apelido in _rotulados(registros, gabarito):
        resultado.por_apelido.setdefault(apelido, set()).add(r.pseudonimo)
    return resultado


def taxa_nao_atribuido(registros: list[Registro]) -> tuple[int, int, float]:
    """(saídas, saídas sem par, fração). Só saída pode ficar sem par."""
    saidas = [r for r in registros if r.direcao is Direcao.SAIDA]
    sem_par = sum(1 for r in saidas if not r.atribuido)
    return len(saidas), sem_par, (sem_par / len(saidas) if saidas else 0.0)


def permanencias(registros: list[Registro]) -> list[Permanencia]:
    """Pares entrada→saída de cada pseudônimo, na ordem do tempo.

    Uma entrada sem saída (ainda dentro, ou saída perdida) não vira par. Duas
    entradas seguidas mantêm a última: a anterior teve a saída perdida.
    """
    por_pessoa: dict[str, list[Registro]] = defaultdict(list)
    for r in registros:
        if r.pseudonimo is not None:
            por_pessoa[r.pseudonimo].append(r)

    pares: list[Permanencia] = []
    for pseudonimo, lista in por_pessoa.items():
        aberta: datetime | None = None
        for r in sorted(lista, key=lambda x: x.instante):
            if r.direcao is Direcao.ENTRADA:
                aberta = r.instante
            elif aberta is not None:
                pares.append(Permanencia(pseudonimo, aberta, r.instante))
                aberta = None
    return sorted(pares, key=lambda p: p.entrada)


def resumo(registros: list[Registro], gabarito: dict[str, str] | None = None) -> dict:
    """Os números de uma execução numa tabela só, para relatório e varredura."""
    saidas, sem_par, taxa = taxa_nao_atribuido(registros)
    pessoas = {r.pseudonimo for r in registros if r.pseudonimo is not None}
    perms = permanencias(registros)
    linhas = {
        "travessias": len(registros),
        "pessoas": len(pessoas),
        "saidas": saidas,
        "sem_par": sem_par,
        "taxa_sem_par": taxa,
        "permanencias": len(perms),
        "permanencia_media_min": (
            sum(p.segundos for p in perms) / len(perms) / 60 if perms else 0.0
        ),
    }
    if gabarito:
        pu = pureza(registros, gabarito)
        fr = fragmentacao(registros, gabarito)
        linhas.update({
            "rotuladas": pu.total,
            "pureza": pu.taxa,
            "confusoes": pu.confusoes,
            "pessoas_reais": fr.pessoas,
            "fragmentacao": fr.media,
            "divididas": fr.divididas,
        })
    return linhas
