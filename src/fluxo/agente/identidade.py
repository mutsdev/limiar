"""A camada de identidade do agente: quem cruzou é quem, entre os que estão dentro.

Fica em `agente/` porque é orquestração: junta o extrator (`visao`), a galeria
(`reid`), a trilha (`avaliacao`) e o remetente. Nenhum dos quatro conhece os
outros.

O custo é controlado por construção. Recortar é fatiar um array — barato, e
acontece para todo mundo visível, 1 quadro em N. A rede só roda quando alguém
CRUZA a linha, e só nos recortes daquela pessoa: um lote pequeno por
travessia, zero por quadro.

Com `identidade=None`, o processador não passa por aqui. A contagem de
produção continua a mesma.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, data_de_referencia
from fluxo.dominio.identidade import PessoaSessao, Vinculo
from fluxo.dominio.rastro import Rastro
from fluxo.reid.assinatura import Assinatura, media
from fluxo.reid.galeria import Decisao, Galeria

# Onde vão as miniaturas de quem saiu sem par.
PASTA_SEM_PAR = "_sem_par"


def _gravar_jpg(caminho: Path, imagem) -> None:
    import cv2

    caminho.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(caminho), imagem)


@dataclass(slots=True)
class _Recorte:
    imagem: object
    area: float  # da caixa original: maior = mais perto da câmera = mais nítido


@dataclass
class Identidade:
    camera_id: str
    extrator: object  # visao.aparencia.Extrator, ou um dublê nos testes
    galeria: Galeria
    recortes_por_track: int = 5
    intervalo_recorte_quadros: int = 3
    # Track sem detecção há mais que isto é esquecido — o mesmo prazo da
    # LinhaDeContagem, para os dois não discordarem sobre quem ainda existe.
    esquecer_apos_quadros: int = 60
    remetente: object | None = None
    # Miniaturas só saem quando esta pasta é informada (--guardar-recortes).
    # Em operação é None, e nenhuma imagem toca o disco.
    pasta_recortes: Path | None = None
    trilha: object | None = None
    registrador: logging.Logger | None = None
    gravar_imagem: Callable[[Path, object], None] = _gravar_jpg
    guardar_decisoes: bool = True

    decisoes: list[Decisao] = field(default_factory=list, init=False)
    pessoas_enviadas: int = field(default=0, init=False)
    vinculos_enviados: int = field(default=0, init=False)
    sem_recorte: int = field(default=0, init=False)

    _buffers: dict[int, deque] = field(default_factory=dict, init=False)
    _visto_em: dict[int, int] = field(default_factory=dict, init=False)
    _recortes_pendentes: dict[str, _Recorte] = field(default_factory=dict, init=False)
    _ultimo_instante: datetime | None = field(default=None, init=False)

    # ------------------------------------------------------------------

    def observar(
        self,
        quadro,
        rastros: list[Rastro],
        novos: list[EventoCruzamento],
        avisar: Callable[[str], None] | None = None,
    ) -> list[Decisao]:
        """Um quadro por vez, depois da linha de contagem."""
        instante = quadro.instante
        self._ultimo_instante = instante
        decisoes = self.galeria.preparar(instante)

        for r in rastros:
            self._visto_em[r.id_local] = quadro.indice
        if quadro.indice % self.intervalo_recorte_quadros == 0:
            for r in rastros:
                imagem = self.extrator.recortar(quadro.imagem, r.caixa)
                if imagem is None:
                    continue
                fila = self._buffers.get(r.id_local)
                if fila is None:
                    fila = self._buffers[r.id_local] = deque(maxlen=self.recortes_por_track)
                fila.append(_Recorte(imagem, _area(r.caixa)))

        for e in novos:
            assinatura, melhor = self._assinatura_de(quadro, rastros, e.track_id_local)
            if assinatura is None:
                # Cruzou sem nunca ter sido recortado (track novo demais, ou
                # caixa sem área). Contar continua certo; identidade, não há.
                self.sem_recorte += 1
                continue
            if self.trilha is not None:
                self.trilha.gravar_assinatura(quadro.indice, e.track_id_local, assinatura)
            if melhor is not None and self.pasta_recortes is not None:
                self._recortes_pendentes[e.id_evento] = melhor
            if e.direcao is Direcao.ENTRADA:
                decisoes.append(
                    self.galeria.entrar(e.id_evento, e.track_id_local, assinatura, e.instante)
                )
            else:
                self.galeria.sair(e.id_evento, e.track_id_local, assinatura, e.instante)

        self._esquecer(quadro.indice)
        self._publicar(decisoes, avisar)
        return decisoes

    def fechar(self, avisar: Callable[[str], None] | None = None) -> list[Decisao]:
        """Fim da execução: as saídas que esperavam o lote são resolvidas agora."""
        instante = self._ultimo_instante or datetime.now(FUSO_LOCAL)
        decisoes = self.galeria.fechar(instante)
        self._publicar(decisoes, avisar)
        return decisoes

    def etiquetas(self) -> dict[int, str]:
        return self.galeria.etiquetas()

    def placar(self) -> str:
        g = self.galeria
        return (
            f"pessoas {len(g.pessoas)}  dentro {len(g.dentro)}  "
            f"sem par {g.nao_atribuidas}  fila {g.pendentes}"
        )

    # ------------------------------------------------------------------

    def _assinatura_de(
        self, quadro, rastros: list[Rastro], id_local: int | None
    ) -> tuple[Assinatura | None, _Recorte | None]:
        if id_local is None:
            return None, None
        recortes = list(self._buffers.get(id_local, ()))
        # O quadro do cruzamento entra sempre, mesmo fora do intervalo: é o
        # instante que o evento descreve.
        for r in rastros:
            if r.id_local == id_local:
                imagem = self.extrator.recortar(quadro.imagem, r.caixa)
                if imagem is not None:
                    recortes.append(_Recorte(imagem, _area(r.caixa)))
                break
        if not recortes:
            return None, None
        vetores = self.extrator.extrair([r.imagem for r in recortes])
        if not vetores:
            return None, None
        melhor = max(recortes, key=lambda r: r.area)
        return media(vetores), melhor

    def _esquecer(self, quadro: int) -> None:
        ativos = {
            id_local for id_local, visto in self._visto_em.items()
            if quadro - visto <= self.esquecer_apos_quadros
        }
        for id_local in list(self._visto_em):
            if id_local not in ativos:
                del self._visto_em[id_local]
                self._buffers.pop(id_local, None)
        self.galeria.esquecer(ativos)

    def _publicar(self, decisoes: list[Decisao], avisar: Callable[[str], None] | None) -> None:
        if not decisoes:
            return
        pessoas: list[PessoaSessao] = []
        vinculos: list[Vinculo] = []
        for d in decisoes:
            data_ref = data_de_referencia(d.instante)
            if d.pessoa_nova and d.pseudonimo is not None:
                p = self.galeria.pessoas[d.pseudonimo]
                pessoas.append(PessoaSessao(
                    camera_id=self.camera_id, data_ref=data_ref, pseudonimo=d.pseudonimo,
                    primeiro_visto=p.primeiro_visto, ultimo_visto=p.ultimo_visto,
                ))
            vinculos.append(Vinculo(
                id_evento=d.id_evento, camera_id=self.camera_id, data_ref=data_ref,
                pseudonimo=d.pseudonimo, similaridade=d.similaridade,
                atribuido=d.atribuido, metodo=d.metodo,
            ))
            self._gravar_recorte(d, data_ref)
            self._avisar(avisar, d)
            if self.guardar_decisoes:
                self.decisoes.append(d)

        if self.remetente is not None:
            if pessoas and self.remetente.registrar_pessoas(pessoas):
                self.pessoas_enviadas += len(pessoas)
            if vinculos and self.remetente.enviar_vinculos(vinculos):
                self.vinculos_enviados += len(vinculos)

    def _gravar_recorte(self, d: Decisao, data_ref) -> None:
        recorte = self._recortes_pendentes.pop(d.id_evento, None)
        if recorte is None or self.pasta_recortes is None:
            return
        raiz = Path(self.pasta_recortes) / data_ref.isoformat() / self.camera_id
        pasta = raiz / (d.pseudonimo or PASTA_SEM_PAR)
        # O track no nome evita colisão quando duas pessoas cruzam no mesmo
        # segundo; o id_evento fica no índice, que é o que o gabarito usa.
        nome = f"{d.instante:%H%M%S}_{d.direcao.value}_t{d.id_local}.jpg"
        self.gravar_imagem(pasta / nome, recorte.imagem)
        registrar_no_indice(raiz / ARQUIVO_INDICE, d, pasta.name, nome)

    def _avisar(self, avisar: Callable[[str], None] | None, d: Decisao) -> None:
        sim = f" {d.similaridade:.2f}" if d.similaridade is not None else ""
        quem = d.pseudonimo or "?"
        mensagem = (
            f"  {d.instante:%H:%M:%S}  {d.direcao.value:<7} track {d.id_local} "
            f"-> {quem:<4} ({d.metodo}{sim})"
        )
        if self.registrador is not None:
            self.registrador.info(mensagem)
        elif avisar is not None:
            avisar(mensagem)


def _area(caixa) -> float:
    x1, y1, x2, y2 = caixa
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


# Uma linha por miniatura gravada. É o que liga a imagem que o João Pedro vai
# olhar ao id_evento que o relatório usa — sem isto o gabarito não fecha.
ARQUIVO_INDICE = "indice.csv"
COLUNAS_INDICE = ["id_evento", "instante", "direcao", "pseudonimo", "metodo", "arquivo"]


def registrar_no_indice(caminho: Path, d: Decisao, pasta: str, nome: str) -> None:
    import csv

    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists()
    with caminho.open("a", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        if novo:
            escritor.writerow(COLUNAS_INDICE)
        escritor.writerow([
            d.id_evento, d.instante.isoformat(), d.direcao.value,
            d.pseudonimo or "", d.metodo, f"{pasta}/{nome}",
        ])
