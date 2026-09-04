"""Mantém os processos do Limiar de pé.

O Agendador de Tarefas só precisa lançar o supervisor uma vez, no logon; daí
em diante, relançar filho morto é trabalho daqui — com recuo exponencial,
porque um processo que morre ao nascer não melhora sendo relançado no ato, e
com o recuo zerado depois de um período estável, porque uma queda isolada às
14h não deve penalizar a queda seguinte às 22h.

A lógica é pura de propósito: `lancador` e `relogio` são injetáveis, e os
testes exercitam morte, recuo e estabilidade sem subprocesso nenhum.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class ProcessoGerido:
    nome: str
    comando: list[str]
    log: Path
    cwd: Path | None = None
    # Espaço entre os irmãos na subida: o serviço primeiro, o agente e o
    # painel depois — evita o ruído de "serviço fora do ar" na largada.
    atraso_inicial_s: float = 0.0
    espera_inicial_s: float = 1.0
    espera_maxima_s: float = 60.0
    # Vivo por este tempo = estável; o recuo volta ao início.
    estavel_apos_s: float = 300.0
    # Sonda de vida: `poll()` só vê processo morto. Um agente preso numa
    # inferência, ou um uvicorn que parou de responder, continua "vivo" para
    # o sistema. A sonda pergunta de verdade (HTTP, pulso em arquivo); três
    # "não" seguidos e o processo é derrubado e relançado como se tivesse
    # morrido. Só começa depois de `sonda_apos_s`, porque subir o torch num
    # PC fraco leva minutos e isso não é travamento.
    sonda: Callable[[], bool] | None = None
    sonda_apos_s: float = 120.0
    sonda_intervalo_s: float = 30.0
    sonda_falhas_max: int = 3

    processo: object | None = field(default=None, init=False)
    lancamentos: int = field(default=0, init=False)
    espera_atual_s: float = field(default=0.0, init=False)
    nasceu_em: float = field(default=0.0, init=False)
    proximo_lancamento_em: float | None = field(default=None, init=False)
    falhas_sonda: int = field(default=0, init=False)
    ultima_sonda_em: float | None = field(default=None, init=False)


# O stdout/stderr cru dos filhos não passa pelo logging com rotação; sem um
# teto, o do Streamlit é o arquivo que enche o disco numa operação de meses.
LIMITE_SAIDA_LOG = 20 * 1024 * 1024


def rotacionar_se_grande(arquivo: Path, limite_bytes: int = LIMITE_SAIDA_LOG) -> bool:
    """Guarda uma geração (`.1`) e recomeça do zero quando o arquivo passa do teto."""
    try:
        if arquivo.stat().st_size <= limite_bytes:
            return False
        arquivo.replace(arquivo.with_name(arquivo.name + ".1"))
        return True
    except OSError:
        return False


def _lancar_subprocesso(p: ProcessoGerido):
    p.log.parent.mkdir(parents=True, exist_ok=True)
    rotacionar_se_grande(p.log)
    # Sem PYTHONIOENCODING o filho herda cp1252 ao escrever em arquivo, e o
    # primeiro print com acento derruba o processo — a armadilha clássica
    # deste Windows.
    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with p.log.open("ab") as saida:
        return subprocess.Popen(
            p.comando,
            stdout=saida,
            stderr=subprocess.STDOUT,
            cwd=str(p.cwd) if p.cwd else None,
            env=ambiente,
        )


class Supervisor:
    def __init__(
        self,
        processos: list[ProcessoGerido],
        registrador,
        lancador: Callable[[ProcessoGerido], object] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        tarefa_diaria: Callable[[], None] | None = None,
        hoje: Callable[[], date] = date.today,
        observadores: list[Callable[[], None]] | None = None,
    ) -> None:
        self.processos = processos
        self._log = registrador
        self._lancador = lancador or _lancar_subprocesso
        self._relogio = relogio
        self._tarefa_diaria = tarefa_diaria
        self._hoje = hoje
        self._tarefa_rodou_em: date | None = None
        # Rodam a cada passo, depois dos filhos: o anunciador do túnel, por
        # exemplo. Erro num observador é logado e não derruba a vigilância.
        self._observadores = list(observadores or [])

    def passo(self) -> None:
        """Uma rodada de vigilância: relança mortos, respeitando o recuo."""
        agora = self._relogio()
        for p in self.processos:
            if p.processo is not None:
                if p.processo.poll() is None:
                    if p.espera_atual_s and agora - p.nasceu_em >= p.estavel_apos_s:
                        p.espera_atual_s = 0.0
                    self._sondar(p, agora)
                    continue
                codigo = p.processo.poll()
                self._log.warning(
                    "%s morreu (código %s) após %.0fs de vida",
                    p.nome, codigo, agora - p.nasceu_em,
                )
                p.processo = None
                self._recuar(p, agora)

            if p.proximo_lancamento_em is None:
                p.proximo_lancamento_em = agora + p.atraso_inicial_s
            if agora >= p.proximo_lancamento_em:
                self._lancar(p, agora)

        self._rodar_tarefa_diaria()
        for observador in self._observadores:
            try:
                observador()
            except Exception:
                self._log.exception("Observador %r falhou", observador)

    def _sondar(self, p: ProcessoGerido, agora: float) -> None:
        if p.sonda is None or agora - p.nasceu_em < p.sonda_apos_s:
            return
        if p.ultima_sonda_em is not None and agora - p.ultima_sonda_em < p.sonda_intervalo_s:
            return
        p.ultima_sonda_em = agora
        try:
            respondeu = bool(p.sonda())
        except Exception:
            respondeu = False
        if respondeu:
            p.falhas_sonda = 0
            return
        p.falhas_sonda += 1
        self._log.warning(
            "%s não respondeu à sonda (%d/%d)", p.nome, p.falhas_sonda, p.sonda_falhas_max
        )
        if p.falhas_sonda < p.sonda_falhas_max:
            return
        self._log.warning(
            "%s está de pé mas não responde há %.0fs; derrubando para relançar",
            p.nome, p.sonda_falhas_max * p.sonda_intervalo_s,
        )
        self._derrubar(p.processo)
        p.processo = None
        p.falhas_sonda = 0
        self._recuar(p, agora)

    @staticmethod
    def _derrubar(processo) -> None:
        try:
            processo.terminate()
        except OSError:
            pass
        try:
            processo.wait(timeout=10)
        except Exception:
            try:
                processo.kill()
            except OSError:
                pass

    def rodar(
        self, intervalo_s: float = 5.0, espera: Callable[[float], None] = time.sleep
    ) -> None:
        try:
            while True:
                self.passo()
                espera(intervalo_s)
        finally:
            self.encerrar()

    def encerrar(self) -> None:
        """Derruba os filhos na ordem inversa da subida."""
        vivos = [
            p for p in reversed(self.processos)
            if p.processo is not None and p.processo.poll() is None
        ]
        for p in vivos:
            self._log.info("Encerrando %s", p.nome)
            self._derrubar(p.processo)

    def _lancar(self, p: ProcessoGerido, agora: float) -> None:
        try:
            p.processo = self._lancador(p)
        except OSError as erro:
            self._log.error("Não consegui lançar %s: %s", p.nome, erro)
            self._recuar(p, agora)
            return
        p.lancamentos += 1
        p.nasceu_em = agora
        p.falhas_sonda = 0
        p.ultima_sonda_em = None
        self._log.info(
            "%s lançado (pid %s)%s",
            p.nome, getattr(p.processo, "pid", "?"),
            f" — relançamento nº {p.lancamentos - 1}" if p.lancamentos > 1 else "",
        )

    def _recuar(self, p: ProcessoGerido, agora: float) -> None:
        p.espera_atual_s = (
            p.espera_inicial_s
            if p.espera_atual_s == 0.0
            else min(p.espera_atual_s * 2, p.espera_maxima_s)
        )
        p.proximo_lancamento_em = agora + p.espera_atual_s

    def _rodar_tarefa_diaria(self) -> None:
        if self._tarefa_diaria is None:
            return
        dia = self._hoje()
        if dia == self._tarefa_rodou_em:
            return
        # Marca antes de tentar: uma tarefa que falha volta amanhã, com o erro
        # no log — tentar de novo a cada passo viraria spam de exceção.
        self._tarefa_rodou_em = dia
        try:
            self._tarefa_diaria()
            self._log.info("Tarefa diária executada (%s)", dia)
        except Exception:
            self._log.exception("Tarefa diária falhou; nova tentativa amanhã")
