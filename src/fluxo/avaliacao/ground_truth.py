"""Carrega a referência contra a qual o contador é medido.

Duas fontes, porque há duas perguntas diferentes:

* **CSV** — duas pessoas contando à mão no vídeo da porta real. Responde
  "quanto o sistema erra naquela porta". É a referência que vale para a meta
  dos 10%.
* **MOTChallenge** — anotação humana quadro a quadro de sequências públicas.
  Responde "quanto a detecção imperfeita custa", porque as trajetórias
  anotadas passam pela MESMA linha de contagem, com os mesmos limiares. Só
  uma variável muda: a qualidade da visão.

Este módulo não importa cv2 nem numpy — roda sem o extra `visao` instalado.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

from fluxo.dominio.rastro import Rastro

# Colunas do gt.txt do MOTChallenge:
#   frame, id, x, y, largura, altura, conf, classe, visibilidade
CLASSE_PEDESTRE = 1


# --------------------------------------------------------------------------
# Contagem manual (CSV)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContagemManual:
    """A contagem de referência feita por pessoas, minuto a minuto."""

    por_minuto: dict[int, tuple[int, int]]
    origem: str = ""

    @property
    def entradas(self) -> int:
        return sum(e for e, _ in self.por_minuto.values())

    @property
    def saidas(self) -> int:
        return sum(s for _, s in self.por_minuto.values())

    def entradas_por_minuto(self) -> dict[int, int]:
        return {m: e for m, (e, _) in self.por_minuto.items()}

    def saidas_por_minuto(self) -> dict[int, int]:
        return {m: s for m, (_, s) in self.por_minuto.items()}


class GroundTruthInvalido(Exception):
    """O arquivo de referência não está no formato esperado."""


def carregar_csv(caminho: str | Path) -> ContagemManual:
    """Lê `minuto,entradas,saidas` — o formato de docs/avaliacao.md.

    Por minuto, e não só o total, porque totais batem por compensação: uma
    contagem a mais no minuto 2 e uma a menos no minuto 9 dão um total
    perfeito e escondem dois erros.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise GroundTruthInvalido(f"Arquivo não encontrado: {caminho}")

    por_minuto: dict[int, tuple[int, int]] = {}
    for numero, linha in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(), start=1
    ):
        texto = linha.strip()
        if not texto or texto.startswith("#"):
            continue
        campos = [c.strip() for c in texto.split(",")]
        if campos[0].lower() in ("minuto", "minute"):  # cabeçalho
            continue
        if len(campos) < 3:
            raise GroundTruthInvalido(
                f"{caminho}:{numero} tem {len(campos)} campos; esperado "
                f"minuto,entradas,saidas"
            )
        try:
            minuto, entradas, saidas = (int(campos[0]), int(campos[1]), int(campos[2]))
        except ValueError as erro:
            raise GroundTruthInvalido(f"{caminho}:{numero} não é numérico: {texto}") from erro
        if minuto in por_minuto:
            raise GroundTruthInvalido(f"{caminho}:{numero} repete o minuto {minuto}")
        por_minuto[minuto] = (entradas, saidas)

    if not por_minuto:
        raise GroundTruthInvalido(f"{caminho} não tem nenhuma linha de contagem.")
    return ContagemManual(por_minuto, origem=str(caminho))


# --------------------------------------------------------------------------
# MOTChallenge
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SequenciaMOT:
    """Uma sequência do MOTChallenge, com a anotação já em forma de rastro."""

    nome: str
    caminho: Path
    fps: float = 25.0
    quadros: int = 0
    largura: int = 0
    altura: int = 0
    por_quadro: dict[int, list[Rastro]] = field(default_factory=dict)

    @property
    def padrao_imagens(self) -> str:
        """Padrão que o cv2.VideoCapture entende como sequência de imagens."""
        return str(self.caminho / "img1" / "%06d.jpg")

    @property
    def pessoas(self) -> int:
        return len({r.id_local for lista in self.por_quadro.values() for r in lista})

    def rastros(self, quadro: int) -> list[Rastro]:
        return self.por_quadro.get(quadro, [])


def _ler_seqinfo(caminho: Path) -> dict[str, str]:
    arquivo = caminho / "seqinfo.ini"
    if not arquivo.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(arquivo, encoding="utf-8")
    return dict(parser["Sequence"]) if parser.has_section("Sequence") else {}


def carregar_mot(caminho: str | Path, visibilidade_minima: float = 0.0) -> SequenciaMOT:
    """Lê `<sequencia>/gt/gt.txt` e devolve os rastros anotados por quadro.

    Duas filtragens que não são opcionais:

    * `conf == 0` marca região a ignorar na anotação. Contá-la produziria
      travessias que o anotador explicitamente disse para desconsiderar.
    * `classe != 1` são veículos, bicicletas e pessoas em pose sentada. Só a
      classe 1 é pedestre.
    """
    caminho = Path(caminho)
    arquivo = caminho / "gt" / "gt.txt"
    if not arquivo.exists():
        raise GroundTruthInvalido(
            f"Não achei {arquivo}. Sequências de TESTE do MOTChallenge não têm "
            f"anotação — use as de treino."
        )

    info = _ler_seqinfo(caminho)
    sequencia = SequenciaMOT(
        nome=info.get("name", caminho.name),
        caminho=caminho,
        fps=float(info.get("framerate", 25)),
        quadros=int(info.get("seqlength", 0)),
        largura=int(info.get("imwidth", 0)),
        altura=int(info.get("imheight", 0)),
    )

    for numero, linha in enumerate(
        arquivo.read_text(encoding="utf-8").splitlines(), start=1
    ):
        texto = linha.strip()
        if not texto:
            continue
        campos = texto.split(",")
        if len(campos) < 6:
            raise GroundTruthInvalido(f"{arquivo}:{numero} tem campos de menos: {texto}")

        try:
            quadro = int(float(campos[0]))
            identidade = int(float(campos[1]))
            x, y, largura, altura = (float(c) for c in campos[2:6])
            conf = float(campos[6]) if len(campos) > 6 else 1.0
            classe = int(float(campos[7])) if len(campos) > 7 else CLASSE_PEDESTRE
            visibilidade = float(campos[8]) if len(campos) > 8 else 1.0
        except ValueError:
            # Linha corrompida: descartar uma é melhor que abortar a sequência.
            continue

        if conf == 0 or classe != CLASSE_PEDESTRE or visibilidade < visibilidade_minima:
            continue

        sequencia.por_quadro.setdefault(quadro, []).append(
            Rastro(
                id_local=identidade,
                caixa=(x, y, x + largura, y + altura),
                confianca=1.0,  # anotação humana: não há incerteza a modelar
            )
        )

    if not sequencia.por_quadro:
        raise GroundTruthInvalido(f"{arquivo} não produziu nenhum pedestre válido.")
    if not sequencia.quadros:
        sequencia.quadros = max(sequencia.por_quadro)
    return sequencia


def contar_no_ground_truth(sequencia: SequenciaMOT, linha, instante_inicial) -> list:
    """Passa as trajetórias anotadas pela MESMA linha de contagem.

    É isto que isola a variável: o número que sai daqui é quantas travessias
    existiriam com detecção e rastreio perfeitos, sob exatamente os mesmos
    limiares de histerese, cooldown e idade mínima. A diferença para o número
    medido é o custo da visão imperfeita, e nada mais.
    """
    from datetime import timedelta

    eventos = []
    for quadro in range(1, sequencia.quadros + 1):
        instante = instante_inicial + timedelta(seconds=(quadro - 1) / sequencia.fps)
        eventos.extend(linha.processar(quadro, instante, sequencia.rastros(quadro)))
    return eventos
