"""Fonte ao vivo que não morre.

`FonteDeVideo` tem semântica de arquivo: quando `read()` falha, acabou. Para
stream isso é errado — o ESP32 reinicia, o wifi pisca — e o certo é reconectar
e seguir. Este wrapper compõe a fonte original em vez de mudá-la, para que
arquivo continue terminando no fim.

A leitura roda numa thread que guarda só o quadro mais recente. Isso resolve
dois problemas de uma vez: a CPU processa a ~11 q/s e o stream pode mandar
mais — sem o descarte, o buffer do capture acumula atraso crescente e a
contagem passa a ver o passado; e a espera do consumidor vira watchdog — sem
quadro novo dentro do prazo, a captura é derrubada por baixo e refeita.

Este módulo não importa cv2 de propósito: os testes rodam num ambiente só com
o núcleo, e a fonte real só entra pela fábrica padrão, em tempo de execução.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fluxo.visao.fonte import FonteDeVideo, Quadro


@dataclass(slots=True)
class ConfigFonteViva:
    # Sem quadro novo por este tempo, a conexão é dada como morta — cobre o
    # stream congelado e o `read()` que trava sem retornar.
    timeout_quadro_s: float = 10.0
    espera_inicial_s: float = 1.0
    espera_maxima_s: float = 30.0
    # Lacuna maior que isto invalida o estado de rastreio: quem estava no
    # quadro já não está, e um id reciclado herdaria o lado errado da linha.
    lacuna_para_zerar_s: float = 30.0
    # Sem quadro por este tempo, a fonte desiste: a iteração termina e quem
    # a criou decide o que fazer — procurar a câmera em outro IP, por exemplo.
    # None reconecta para sempre no mesmo endereço.
    desistir_apos_s: float | None = None


class FonteViva:
    """Mesma interface iteradora de `FonteDeVideo`; termina por `fechar()` ou desistindo."""

    def __init__(
        self,
        origem: str | int,
        config: ConfigFonteViva | None = None,
        fabrica: Callable[[], FonteDeVideo] | None = None,
        registrador: logging.Logger | None = None,
        espera: Callable[[float], None] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        pulso: Callable[[], None] | None = None,
    ) -> None:
        self.origem = origem
        self.config = config or ConfigFonteViva()
        self._fabrica = fabrica or self._fabrica_padrao
        self._log = registrador or logging.getLogger(__name__)
        # `espera` e `relogio` são injetáveis para os testes controlarem o
        # tempo. Sem injeção, a espera usa o evento de parada — interrompível,
        # para `fechar()` não esperar um recuo de 30 s terminar.
        self._espera = espera
        self._relogio = relogio
        # Batido a cada volta do consumidor, com quadro ou sem: é a prova de
        # vida que o supervisor lê. Do lado do consumidor de propósito — um
        # `processar` travado para de bater; câmera fora do ar não.
        self._pulso = pulso

        self.ao_vivo = True
        self.total_quadros = 0
        self.reconexoes = 0
        self.desistiu = False
        self._iniciado_em = self._relogio()

        self._fila: queue.Queue[Quadro] = queue.Queue(maxsize=1)
        self._parar = threading.Event()
        self._tranca = threading.Lock()
        self._fonte_atual: FonteDeVideo | None = None
        self._indice = 0
        self._ultimo_quadro_em: float | None = None

        self._thread = threading.Thread(
            target=self._ler, daemon=True, name=f"fonte-viva-{origem}"
        )
        self._thread.start()

    def _fabrica_padrao(self) -> FonteDeVideo:
        # MJPEG primeiro, e não por preferência estética: medido contra a
        # câmera real, o VideoCapture lê a 1,1 q/s um stream que o servidor
        # entrega a 16 (ver fonte_mjpeg). A tentativa custa uma conexão, que a
        # própria FonteMjpeg encerra quando o content-type não é multipart.
        if isinstance(self.origem, str) and self.origem.startswith(("http://", "https://")):
            from fluxo.visao.fonte_mjpeg import FonteMjpeg

            try:
                return FonteMjpeg(self.origem, registrador=self._log)
            except ValueError as erro:
                # Só quando a resposta veio e NÃO é multipart. Erro de rede
                # sobe, para a reconexão tentar o MJPEG de novo em vez de
                # cair para sempre no caminho lento.
                self._log.info("%s; lendo com VideoCapture.", erro)

        from fluxo.visao.fonte import FonteDeVideo

        return FonteDeVideo(self.origem)

    # ------------------------------------------------------------------
    # Thread leitora
    # ------------------------------------------------------------------

    def _sem_quadro_ha(self) -> float:
        referencia = self._ultimo_quadro_em
        if referencia is None:
            referencia = self._iniciado_em
        return self._relogio() - referencia

    def _desistir_se_for_a_hora(self) -> bool:
        limite = self.config.desistir_apos_s
        if limite is None or self._sem_quadro_ha() < limite:
            return False
        self._log.error(
            "Nenhum quadro de %s há %.0fs; desistindo deste endereço",
            self.origem, self._sem_quadro_ha(),
        )
        self.desistiu = True
        self._parar.set()
        return True

    def _ler(self) -> None:
        recuo_s = self.config.espera_inicial_s
        while not self._parar.is_set():
            try:
                fonte = self._fabrica()
            except Exception as erro:
                if self._desistir_se_for_a_hora():
                    break
                self._log.warning(
                    "Sem conexão com %s (%s); nova tentativa em %.0fs",
                    self.origem, erro, recuo_s,
                )
                self._pausar(recuo_s)
                recuo_s = min(recuo_s * 2, self.config.espera_maxima_s)
                continue

            with self._tranca:
                self._fonte_atual = fonte
            conectada_em = self._relogio()

            lacuna_s = (
                None
                if self._ultimo_quadro_em is None
                else conectada_em - self._ultimo_quadro_em
            )
            marcar = lacuna_s is not None and lacuna_s > self.config.lacuna_para_zerar_s
            if lacuna_s is not None:
                self.reconexoes += 1
                self._log.info(
                    "Reconectado a %s após lacuna de %.1fs%s",
                    self.origem, lacuna_s,
                    " — estado de rastreio será zerado" if marcar else "",
                )

            try:
                for quadro in fonte:
                    if self._parar.is_set():
                        break
                    self._depositar(
                        replace(quadro, indice=self._indice, apos_lacuna=marcar)
                    )
                    marcar = False
                    self._indice += 1
                    self._ultimo_quadro_em = self._relogio()
                    # Conexão entregando quadro é conexão sã: recuo ao início.
                    recuo_s = self.config.espera_inicial_s
            except Exception as erro:
                self._log.warning("Leitura de %s falhou: %s", self.origem, erro)
            finally:
                with self._tranca:
                    self._fonte_atual = None
                try:
                    fonte.fechar()
                except Exception:
                    pass

            if self._parar.is_set():
                break
            if self._desistir_se_for_a_hora():
                break
            self._log.warning(
                "Stream de %s caiu após %.1fs conectado; reconectando",
                self.origem, self._relogio() - conectada_em,
            )
            self._pausar(recuo_s)
            recuo_s = min(recuo_s * 2, self.config.espera_maxima_s)

    def _depositar(self, quadro: Quadro) -> None:
        try:
            self._fila.put_nowait(quadro)
            return
        except queue.Full:
            pass
        try:
            descartado = self._fila.get_nowait()
            # A marca de lacuna não pode se perder num descarte: ela é o único
            # aviso de que o estado de contagem ficou inválido.
            if descartado.apos_lacuna and not quadro.apos_lacuna:
                quadro = replace(quadro, apos_lacuna=True)
        except queue.Empty:
            pass
        try:
            self._fila.put_nowait(quadro)
        except queue.Full:
            pass

    def _pausar(self, segundos: float) -> None:
        if self._espera is not None:
            self._espera(segundos)
        else:
            self._parar.wait(segundos)

    # ------------------------------------------------------------------
    # Lado do consumidor
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[Quadro]:
        while not self._parar.is_set():
            if self._pulso is not None:
                self._pulso()
            try:
                yield self._fila.get(timeout=self.config.timeout_quadro_s)
            except queue.Empty:
                if self._parar.is_set():
                    break
                # Watchdog: pode ser stream congelado com o `read()` preso lá
                # dentro. Fechar a captura por baixo faz o read falhar e o
                # laço leitor cair no caminho normal de reconexão.
                self._log.warning(
                    "Nenhum quadro de %s em %.0fs; forçando reconexão",
                    self.origem, self.config.timeout_quadro_s,
                )
                self._derrubar_fonte()

    def _derrubar_fonte(self) -> None:
        with self._tranca:
            fonte = self._fonte_atual
        if fonte is not None:
            try:
                fonte.fechar()
            except Exception:
                pass

    def fechar(self) -> None:
        self._parar.set()
        self._derrubar_fonte()
        self._thread.join(timeout=5.0)

    def __enter__(self) -> FonteViva:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    # Espelham a fonte interna quando há uma; os valores de descanso são os
    # mesmos palpites seguros da FonteDeVideo.
    @property
    def fps(self) -> float:
        with self._tranca:
            return self._fonte_atual.fps if self._fonte_atual is not None else 25.0

    @property
    def largura(self) -> int:
        with self._tranca:
            return self._fonte_atual.largura if self._fonte_atual is not None else 0

    @property
    def altura(self) -> int:
        with self._tranca:
            return self._fonte_atual.altura if self._fonte_atual is not None else 0

    def __repr__(self) -> str:
        return f"FonteViva({self.origem!r}, reconexoes={self.reconexoes})"
