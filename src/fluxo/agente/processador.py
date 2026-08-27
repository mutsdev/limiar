"""O laço principal do agente: fonte -> rastreio -> linha -> envio."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from fluxo.agente.remetente import Remetente
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import EventoCruzamento
from fluxo.visao.fonte import FonteDeVideo
from fluxo.visao.rastreador import RastreadorPessoas

# Eventos são acumulados e enviados em lote. Um POST por pessoa seria uma
# viagem de rede por passagem, sem necessidade.
TAMANHO_LOTE = 25


@dataclass
class Resultado:
    quadros: int = 0
    eventos: list[EventoCruzamento] = field(default_factory=list)
    entradas: int = 0
    saidas: int = 0
    segundos: float = 0.0

    @property
    def fps(self) -> float:
        return self.quadros / self.segundos if self.segundos else 0.0


def processar(
    fonte: FonteDeVideo,
    rastreador: RastreadorPessoas,
    linha: LinhaDeContagem,
    remetente: Remetente | None = None,
    gravador=None,
    limite_quadros: int | None = None,
    mostrar_progresso: bool = True,
    janela=None,
    trilha=None,
) -> Resultado:
    """Roda o pipeline inteiro sobre uma fonte de vídeo."""
    import time

    from fluxo.visao import anotador

    resultado = Resultado()
    pendentes: list[EventoCruzamento] = []
    inicio = time.monotonic()

    total = limite_quadros or fonte.total_quadros or None
    barra = tqdm(total=total, unit="q", disable=not mostrar_progresso, leave=False)

    if remetente is not None and remetente.servico_no_ar():
        drenados = remetente.drenar_fila()
        if drenados:
            barra.write(f"Fila local drenada: {drenados} eventos reenviados.")

    try:
        for quadro in fonte:
            if limite_quadros is not None and resultado.quadros >= limite_quadros:
                break

            rastros = rastreador.atualizar(quadro.imagem)

            # Grava ANTES de contar: a trilha registra o que a visão enxergou,
            # e precisa ser independente dos parâmetros de contagem para que o
            # replay possa variá-los.
            if trilha is not None:
                trilha.gravar(quadro.indice, quadro.instante, rastros)

            novos = linha.processar(quadro.indice, quadro.instante, rastros)

            if novos:
                resultado.eventos.extend(novos)
                pendentes.extend(novos)
                for e in novos:
                    barra.write(
                        f"  {e.instante:%H:%M:%S}  {e.direcao.value:<7} "
                        f"track {e.track_id_local}"
                    )

            if remetente is not None and len(pendentes) >= TAMANHO_LOTE:
                remetente.enviar(pendentes)
                pendentes = []

            # Anota uma vez só, e reaproveita o mesmo quadro nos dois destinos.
            if gravador is not None or janela is not None:
                anotador.anotar(quadro.imagem, linha, rastros, quadro.indice)
            if gravador is not None:
                gravador.escrever(quadro.imagem)
            if janela is not None and not janela.mostrar(quadro.imagem):
                barra.write("Interrompido pela janela.")
                break

            resultado.quadros += 1
            barra.update(1)
    finally:
        barra.close()

    if remetente is not None and pendentes:
        remetente.enviar(pendentes)

    resultado.segundos = time.monotonic() - inicio
    resultado.entradas = linha.entradas
    resultado.saidas = linha.saidas
    return resultado


def instante_inicial_de(caminho: Path | str, informado: datetime | None) -> datetime:
    """Quando o vídeo começou.

    Se não for informado, usa a data de modificação do arquivo — que para uma
    gravação é aproximadamente a hora em que ela terminou, mas é melhor que
    inventar "agora" e datar eventos de ontem com a hora de hoje.
    """
    from fluxo.dominio.evento import FUSO_LOCAL

    if informado is not None:
        return informado
    p = Path(caminho)
    if p.exists():
        return datetime.fromtimestamp(p.stat().st_mtime, tz=FUSO_LOCAL)
    return datetime.now(FUSO_LOCAL)


def versao_do_codigo() -> str:
    """Hash curto do commit atual, ou "" se não for um repositório git.

    Vai junto com a medição: sem saber qual código produziu um número, o
    resultado não é reproduzível.
    """
    import subprocess

    try:
        saida = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parents[3],
        )
        return saida.stdout.strip() if saida.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""
