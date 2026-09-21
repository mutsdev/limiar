"""Avisos no celular quando a operação desassistida quebra — e quando não quebra.

O supervisor já sabe relançar filho morto, derrubar filho travado e reconectar
stream caído. O que faltava era alguém do lado de fora saber que isso
aconteceu: em dois dias de operação sem ninguém no laboratório, um agente em
ciclo de relançamento na sexta à noite só seria descoberto na segunda.

O batimento positivo existe pelo mesmo motivo que os alertas. Sem ele,
silêncio no celular é ambíguo — pode ser "está tudo bem" ou "o supervisor
inteiro morreu e não sobrou ninguém para avisar". Com uma mensagem a cada 6 h,
silêncio passa a ser, ele próprio, um alarme.

Como isto NÃO mexe no supervisor: o `Vigia` é um observador comum, dos que
`Supervisor.passo()` chama ao fim de cada volta, e lê os campos públicos
`lancamentos` e `falhas_sonda` de cada `ProcessoGerido`. É a mesma estratégia
do `AnunciadorDeTunel`, que observa o log do cloudflared em vez de exigir um
callback novo lá dentro.

Todo aviso é por TRANSIÇÃO, nunca por estado: câmera muda avisa uma vez ao
ficar muda e uma vez ao voltar. Alerta que se repete a cada 5 s vira ruído, e
ruído no celular é ignorado exatamente como silêncio.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from fluxo.dominio.evento import Origem
from fluxo.operacao.pulso import arquivo_de_quadro, pulso_recente

# Sem quadro por este tempo, a câmera é dada como muda. A `FonteViva` já
# desiste do endereço com 10 min e varre a rede atrás de um IP novo: avisar
# antes disso seria alarme para coisa que se resolve sozinha em dois minutos.
SEM_QUADRO_MAXIMO_S = 900.0

# Carência de partida. Subir torch + ultralytics num PC sem GPU leva minutos
# (e na primeira vez ainda baixa o modelo); antes disso "sem quadro" não é
# falha. Alinhada com o `sonda_apos_s=300.0` do agente, com folga.
CARENCIA_S = 600.0

# De quanto em quanto tempo sai o "está tudo bem, N entradas hoje".
BATIMENTO_S = 6 * 3600.0


def enviar_ntfy(
    url_aviso: str,
    texto: str,
    titulo: str = "Limiar",
    tags: str = "",
    prioridade: str = "",
    clique: str = "",
) -> None:
    """Publica uma linha num tópico ntfy.sh. Levanta se a rede falhar.

    Deliberadamente burra: quem chama é que decide engolir o erro. Um aviso
    que não sai não pode derrubar a contagem que ele estava vigiando.

    O `texto` vai no corpo, em UTF-8, e aceita acento. O `titulo` vai num
    cabeçalho HTTP, que não aceita: por isso os títulos daqui são ASCII.
    """
    import httpx

    cabecalhos = {"Title": titulo}
    if tags:
        cabecalhos["Tags"] = tags
    if prioridade:
        cabecalhos["Priority"] = prioridade
    if clique:
        cabecalhos["Click"] = clique

    httpx.post(
        url_aviso, content=texto.encode(), headers=cabecalhos, timeout=10.0
    ).raise_for_status()


def totais_do_dia(
    conn: sqlite3.Connection, dia: date, camera_id: str | None = None
) -> tuple[int, int]:
    """(entradas, saídas) do dia, direto do SQL.

    Pelo `repositorio.contagem_diaria` e não pelo caminho pandas do
    `consultas.resumo_diario`: o batimento roda dentro do supervisor, que é o
    processo que precisa continuar leve e de pé enquanto todos os outros
    tropeçam.

    O filtro `origem=VISAO` é o padrão do repositório e fica como está — dado
    de simulação não pode entrar num aviso que você vai ler como medição.
    """
    from fluxo.persistencia import repositorio

    entradas = saidas = 0
    for linha in repositorio.contagem_diaria(conn, dia, dia, camera_id, origem=Origem.VISAO):
        if linha["direcao"] == "ENTRADA":
            entradas += int(linha["total"])
        elif linha["direcao"] == "SAIDA":
            saidas += int(linha["total"])
    return entradas, saidas


def _totais_do_banco(camera_id: str | None) -> tuple[int, int]:
    """Abre, lê e fecha. Conexão de SQLite não atravessa dias nem threads."""
    from fluxo.persistencia import repositorio

    conn = repositorio.conectar()
    try:
        return totais_do_dia(conn, date.today(), camera_id)
    finally:
        conn.close()


class Vigia:
    """Observador do supervisor que avisa por transição.

    `url_aviso` vazia = não avisa ninguém, mesma convenção do túnel: o
    `Vigia` continua funcionando e registrando no log, só não manda nada.
    """

    def __init__(
        self,
        processos: Iterable[object],
        camera: str,
        url_aviso: str = "",
        enviar: Callable[..., None] = enviar_ntfy,
        registrador: logging.Logger | None = None,
        relogio: Callable[[], float] = time.monotonic,
        arquivo_quadro: Path | None = None,
        sem_quadro_maximo_s: float = SEM_QUADRO_MAXIMO_S,
        carencia_s: float = CARENCIA_S,
        batimento_s: float = BATIMENTO_S,
        totais: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self.processos = list(processos)
        self.camera = camera
        self.url_aviso = url_aviso
        self._enviar = enviar
        self._log = registrador or logging.getLogger(__name__)
        self._relogio = relogio
        self._arquivo_quadro = arquivo_quadro or arquivo_de_quadro(camera)
        self.sem_quadro_maximo_s = sem_quadro_maximo_s
        self.carencia_s = carencia_s
        self.batimento_s = batimento_s
        self._totais = totais or (lambda: _totais_do_banco(camera))

        self._nasceu_em = self._relogio()
        # O primeiro lançamento de cada filho é a subida normal, não um
        # relançamento: parte-se do que já existe para não avisar na largada.
        self._lancamentos = {p.nome: p.lancamentos for p in self.processos}
        self._sondas = {p.nome: p.falhas_sonda for p in self.processos}
        self.camera_muda = False
        self._ultimo_batimento_em: float | None = None

    def __call__(self) -> None:
        self.observar()

    def observar(self) -> list[str]:
        """Uma volta de vigilância. Devolve os avisos emitidos, para os testes."""
        agora = self._relogio()
        avisos: list[str] = []

        for p in self.processos:
            avisos += self._ver_processo(p)
        avisos += self._ver_camera(agora)
        avisos += self._ver_batimento(agora)
        return avisos

    # ------------------------------------------------------------------

    def _ver_processo(self, p) -> list[str]:
        avisos = []
        antes = self._lancamentos.get(p.nome, 0)
        if p.lancamentos > antes:
            self._lancamentos[p.nome] = p.lancamentos
            # `lancamentos == 1` é a subida inicial, que não interessa a
            # ninguém. Do segundo em diante, algo derrubou o filho.
            if p.lancamentos > 1:
                avisos.append(
                    self._avisar(
                        f"{p.nome} caiu e foi relançado (nº {p.lancamentos - 1})",
                        titulo="Limiar reiniciou um processo",
                        tags="warning",
                    )
                )

        falhas_antes = self._sondas.get(p.nome, 0)
        self._sondas[p.nome] = p.falhas_sonda
        # Só a borda de subida: 1, 2 e 3 falhas seguidas viram um aviso só.
        if p.falhas_sonda > 0 and falhas_antes == 0:
            avisos.append(
                self._avisar(
                    f"{p.nome} está de pé mas não responde à sonda",
                    titulo="Limiar sem resposta",
                    tags="warning",
                )
            )
        return avisos

    def _ver_camera(self, agora: float) -> list[str]:
        if agora - self._nasceu_em < self.carencia_s:
            return []
        chegando = pulso_recente(self._arquivo_quadro, self.sem_quadro_maximo_s)
        if not chegando and not self.camera_muda:
            self.camera_muda = True
            minutos = self.sem_quadro_maximo_s / 60
            return [
                self._avisar(
                    f"Nenhum quadro da câmera {self.camera} há mais de "
                    f"{minutos:.0f} min. O agente está vivo; a câmera, não.",
                    titulo="Limiar sem imagem",
                    tags="rotating_light",
                    prioridade="high",
                )
            ]
        if chegando and self.camera_muda:
            self.camera_muda = False
            return [
                self._avisar(
                    f"A câmera {self.camera} voltou a entregar quadros.",
                    titulo="Limiar voltou",
                    tags="white_check_mark",
                )
            ]
        return []

    def _ver_batimento(self, agora: float) -> list[str]:
        if self._ultimo_batimento_em is not None and (
            agora - self._ultimo_batimento_em < self.batimento_s
        ):
            return []
        # O primeiro sai na largada de propósito: é a confirmação de que o
        # canal de aviso funciona, no momento em que você ainda está lá.
        self._ultimo_batimento_em = agora
        try:
            entradas, saidas = self._totais()
        except Exception as erro:
            self._log.warning("Não consegui ler os totais para o batimento: %s", erro)
            return []
        return [
            self._avisar(
                f"{self.camera}: {entradas} entradas e {saidas} saídas hoje.",
                titulo="Batimento do Limiar",
                tags="bar_chart",
            )
        ]

    def _avisar(self, texto: str, titulo: str, tags: str = "", prioridade: str = "") -> str:
        self._log.info("Aviso: %s", texto)
        if not self.url_aviso:
            return texto
        try:
            self._enviar(self.url_aviso, texto, titulo=titulo, tags=tags, prioridade=prioridade)
        except Exception as erro:
            # O aviso é conveniência; a contagem não pode cair por causa dele.
            self._log.warning("Não consegui avisar %s: %s", self.url_aviso, erro)
        return texto
