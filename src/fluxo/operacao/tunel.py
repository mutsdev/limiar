"""Túnel para o painel chegar a quem está fora da rede do laboratório.

Um "quick tunnel" do Cloudflare não pede conta, domínio nem admin: o
`cloudflared` abre uma conexão de saída e recebe uma URL pública aleatória
em `trycloudflare.com`. O preço é que a URL muda a cada reinício — e ninguém
está no laboratório para ler o log. Por isso o supervisor observa a saída do
túnel e, quando aparece uma URL nova, manda para `URL_AVISO` (um tópico do
ntfy.sh que o celular assina).

Tudo o que sai por aqui é o painel, que exige senha (`SENHA_PAINEL`). O
serviço FastAPI continua em localhost.
"""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from fluxo import config

REGEX_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
NOME_EXE = "cloudflared.exe"
URL_DOWNLOAD = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)


def localizar_cloudflared(
    explicito: str | None = None,
    pasta: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path | None:
    """`.env` primeiro, PATH depois, e por fim a pasta de ferramentas do projeto."""
    explicito = config.CLOUDFLARED if explicito is None else explicito
    if explicito:
        caminho = Path(explicito)
        return caminho if caminho.exists() else None
    no_path = which("cloudflared")
    if no_path:
        return Path(no_path)
    pasta = config.CAMINHO_FERRAMENTAS if pasta is None else pasta
    candidato = pasta / NOME_EXE
    return candidato if candidato.exists() else None


def comando_quick_tunnel(exe: Path, porta: int = 8501, host: str = "127.0.0.1") -> list[str]:
    # --no-autoupdate: um binário que se troca sozinho no meio da madrugada é
    # exatamente o tipo de surpresa que a operação não quer.
    return [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://{host}:{porta}"]


def extrair_url(texto: str) -> str | None:
    """A última URL pública que apareceu no texto, ou None."""
    achadas = REGEX_URL.findall(texto)
    return achadas[-1] if achadas else None


def enviar_ntfy(url_aviso: str, url: str) -> None:
    import httpx

    httpx.post(
        url_aviso,
        content=f"Painel do Limiar: {url}".encode(),
        headers={"Title": "Limiar no ar", "Click": url, "Tags": "door"},
        timeout=10.0,
    ).raise_for_status()


class AnunciadorDeTunel:
    """Lê a saída do cloudflared aos poucos e anuncia cada URL nova uma vez."""

    def __init__(
        self,
        log: Path,
        url_aviso: str = "",
        enviar: Callable[[str, str], None] = enviar_ntfy,
        registrador: logging.Logger | None = None,
        arquivo_url: Path | None = None,
    ) -> None:
        self.log = log
        self.url_aviso = url_aviso
        self._enviar = enviar
        self._log = registrador or logging.getLogger(__name__)
        self.arquivo_url = arquivo_url
        self.url_atual: str | None = None
        # Começa do fim do que já existe: o log guarda a saída de execuções
        # anteriores, e a URL de ontem está morta — anunciá-la mandaria o
        # celular para um túnel que não existe mais.
        self._posicao = self._tamanho()

    def _tamanho(self) -> int:
        try:
            return self.log.stat().st_size
        except OSError:
            return 0

    def __call__(self) -> None:
        self.observar()

    def observar(self) -> str | None:
        """Consome o que o túnel escreveu desde a última vez. Devolve URL nova, se houve."""
        tamanho = self._tamanho()
        if tamanho < self._posicao:
            # Arquivo rotacionado ou truncado: recomeça do zero.
            self._posicao = 0
        if tamanho == self._posicao:
            return None
        with self.log.open("rb") as f:
            f.seek(self._posicao)
            novo = f.read().decode("utf-8", errors="ignore")
        self._posicao = tamanho

        url = extrair_url(novo)
        if url is None or url == self.url_atual:
            return None
        self.url_atual = url
        self._anunciar(url)
        return url

    def _anunciar(self, url: str) -> None:
        self._log.info("Túnel no ar: %s", url)
        if self.arquivo_url is not None:
            try:
                self.arquivo_url.write_text(url + "\n", encoding="utf-8")
            except OSError:
                pass
        if not self.url_aviso:
            return
        try:
            self._enviar(self.url_aviso, url)
            self._log.info("URL enviada para %s", self.url_aviso)
        except Exception as erro:
            # O aviso é conveniência; a URL continua no log e no arquivo.
            self._log.warning("Não consegui avisar %s: %s", self.url_aviso, erro)
