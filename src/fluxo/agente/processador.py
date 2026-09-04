"""O laço principal do agente: fonte -> rastreio -> linha -> envio."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tqdm import tqdm

from fluxo.agente.remetente import Remetente
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import EventoCruzamento

if TYPE_CHECKING:
    # Só para as anotações: importar de verdade puxaria cv2, e este módulo
    # precisa continuar importável no ambiente de núcleo dos testes.
    from fluxo.visao.fonte import FonteDeVideo
    from fluxo.visao.rastreador import RastreadorPessoas

# Eventos são acumulados e enviados em lote. Um POST por pessoa seria uma
# viagem de rede por passagem, sem necessidade.
TAMANHO_LOTE = 25

# ...mas o lote também vence por tempo. Com pouco movimento, 25 travessias
# levam uma tarde; nesse meio-tempo o painel não vê nada e, se o agente
# morrer, o que estava na memória morre junto — o supervisor relança o
# processo, não a memória.
INTERVALO_ENVIO_S = 30.0


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


def _avisar(barra: tqdm, registrador: logging.Logger | None, mensagem: str) -> None:
    # No uso interativo a mensagem sai pelo tqdm, para não quebrar a barra; no
    # caminho 24h vai para o arquivo de log, porque não há ninguém no console.
    if registrador is not None:
        registrador.info(mensagem)
    else:
        barra.write(mensagem)


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
    escala_placar: float = 1.0,
    registrador: logging.Logger | None = None,
    guardar_eventos: bool = True,
    identidade=None,
    publicador=None,
) -> Resultado:
    """Roda o pipeline inteiro sobre uma fonte de vídeo.

    `guardar_eventos=False` é para a execução contínua: numa fonte que nunca
    acaba, `resultado.eventos` cresceria sem limite. Os totais continuam
    saindo de `linha.entradas`/`linha.saidas`.

    `identidade` é a Etapa 2 (agente.identidade.Identidade). Com None — o
    caso da contagem de produção — este laço não muda em nada.

    `publicador` (visao.quadro_vivo.PublicadorDeQuadro) recebe o quadro
    anotado para a aba "Ao vivo" do painel.
    """
    import time

    resultado = Resultado()
    pendentes: list[EventoCruzamento] = []
    inicio = time.monotonic()

    total = limite_quadros or fonte.total_quadros or None
    barra = tqdm(total=total, unit="q", disable=not mostrar_progresso, leave=False)

    if remetente is not None and remetente.servico_no_ar():
        drenados = remetente.drenar_fila()
        if drenados:
            _avisar(barra, registrador, f"Fila local drenada: {drenados} eventos reenviados.")

    try:
        for quadro in fonte:
            if limite_quadros is not None and resultado.quadros >= limite_quadros:
                break

            # A fonte viva marca o primeiro quadro depois de uma queda longa:
            # quem estava na cena já não está, e id reciclado com lado velho
            # geraria cruzamento fantasma. Zera-se o rastreio, não os totais.
            if getattr(quadro, "apos_lacuna", False):
                _avisar(barra, registrador,
                        "Lacuna longa no stream: zerando rastreador e estados da linha.")
                rastreador.reiniciar()
                linha.zerar_rastros()

            rastros = rastreador.atualizar(quadro.imagem)

            # Grava ANTES de contar: a trilha registra o que a visão enxergou,
            # e precisa ser independente dos parâmetros de contagem para que o
            # replay possa variá-los.
            if trilha is not None:
                trilha.gravar(quadro.indice, quadro.instante, rastros)

            novos = linha.processar(quadro.indice, quadro.instante, rastros)

            if novos:
                if guardar_eventos:
                    resultado.eventos.extend(novos)
                pendentes.extend(novos)
                for e in novos:
                    _avisar(
                        barra, registrador,
                        f"  {e.instante:%H:%M:%S}  {e.direcao.value:<7} "
                        f"track {e.track_id_local}",
                    )

            # Depois da linha, e antes de desenhar: o recorte tem de sair do
            # quadro limpo, não do quadro com caixas em cima.
            if identidade is not None:
                identidade.observar(
                    quadro, rastros, novos,
                    avisar=lambda m: _avisar(barra, registrador, m),
                )

            vencido = bool(pendentes) and (
                (quadro.instante - pendentes[0].instante).total_seconds() >= INTERVALO_ENVIO_S
            )
            if remetente is not None and pendentes and (
                len(pendentes) >= TAMANHO_LOTE or vencido
            ):
                if remetente.enviar(pendentes) and remetente.fila.tamanho:
                    # O serviço voltou: o que ficou preso de uma queda anterior
                    # sai agora, e não só no próximo restart do agente.
                    remetente.drenar_fila()
                pendentes = []

            # Anota uma vez só, e reaproveita o mesmo quadro nos três destinos.
            if gravador is not None or janela is not None or publicador is not None:
                from fluxo.visao import anotador

                anotador.anotar(
                    quadro.imagem, linha, rastros, quadro.indice,
                    extra=identidade.placar() if identidade is not None else "",
                    escala=escala_placar,
                    etiquetas=identidade.etiquetas() if identidade is not None else None,
                )
            if gravador is not None:
                gravador.escrever(quadro.imagem)
            if publicador is not None:
                publicador.publicar(quadro.imagem)
            if janela is not None and not janela.mostrar(quadro.imagem):
                barra.write("Interrompido pela janela.")
                break

            resultado.quadros += 1
            barra.update(1)
    finally:
        barra.close()

    if identidade is not None:
        # Saídas que esperavam companhia no lote são decididas agora.
        identidade.fechar(avisar=lambda m: _avisar(barra, registrador, m))

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
