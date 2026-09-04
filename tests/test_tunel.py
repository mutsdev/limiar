"""Túnel: achar a URL na saída do cloudflared e anunciar cada uma só uma vez."""

from __future__ import annotations

import logging
from pathlib import Path

from fluxo.operacao import tunel

LOG = logging.getLogger("teste-tunel")

SAIDA = """\
2026-09-04T20:01:02Z INF Thank you for trying Cloudflare Tunnel. Do not use it in production.
2026-09-04T20:01:02Z INF Requesting new quick Tunnel on trycloudflare.com...
2026-09-04T20:01:04Z INF +--------------------------------------------------------------+
2026-09-04T20:01:04Z INF |  Your quick Tunnel has been created! Visit it at:            |
2026-09-04T20:01:04Z INF |  https://sunny-frog-mesa-lab.trycloudflare.com                |
2026-09-04T20:01:04Z INF +--------------------------------------------------------------+
"""


class TestExtrair:
    def test_acha_a_url_e_ignora_o_resto(self):
        assert tunel.extrair_url(SAIDA) == "https://sunny-frog-mesa-lab.trycloudflare.com"
        assert tunel.extrair_url("Requesting new quick Tunnel on trycloudflare.com...") is None


class TestLocalizar:
    def test_ordem_env_path_pasta(self, tmp_path):
        exe = tmp_path / "cloudflared.exe"
        exe.write_bytes(b"")
        assert tunel.localizar_cloudflared(str(exe), pasta=tmp_path / "x") == exe
        assert tunel.localizar_cloudflared("", pasta=tmp_path, which=lambda n: None) == exe
        assert tunel.localizar_cloudflared(
            "", pasta=tmp_path, which=lambda n: r"C:\bin\cloudflared.exe"
        ) == Path(r"C:\bin\cloudflared.exe")
        assert tunel.localizar_cloudflared(
            "", pasta=tmp_path / "vazia", which=lambda n: None
        ) is None

    def test_comando_do_quick_tunnel(self):
        comando = tunel.comando_quick_tunnel(Path("cf.exe"), porta=8501)
        assert comando == ["cf.exe", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8501"]


class TestAnunciador:
    def test_anuncia_uma_vez_e_de_novo_so_quando_muda(self, tmp_path):
        log = tmp_path / "tunel.saida.log"
        enviados = []
        anunciador = tunel.AnunciadorDeTunel(
            log, "https://ntfy.sh/limiar-x", enviar=lambda alvo, url: enviados.append((alvo, url)),
            registrador=LOG, arquivo_url=tmp_path / "tunel.url",
        )
        assert anunciador.observar() is None  # sem arquivo ainda

        log.write_text(SAIDA, encoding="utf-8")
        assert anunciador.observar() == "https://sunny-frog-mesa-lab.trycloudflare.com"
        assert anunciador.observar() is None  # nada novo
        assert (tmp_path / "tunel.url").read_text(encoding="utf-8").strip().endswith(
            "trycloudflare.com"
        )

        # Túnel caiu e voltou com outra URL: anuncia a nova.
        with log.open("a", encoding="utf-8") as f:
            f.write("INF |  https://other-name-here.trycloudflare.com  |\n")
        assert anunciador.observar() == "https://other-name-here.trycloudflare.com"
        assert [url for _, url in enviados] == [
            "https://sunny-frog-mesa-lab.trycloudflare.com",
            "https://other-name-here.trycloudflare.com",
        ]

    def test_ignora_o_que_ja_estava_no_log_ao_nascer(self, tmp_path):
        # O log guarda a saída da execução anterior; aquela URL está morta.
        log = tmp_path / "tunel.saida.log"
        log.write_text(SAIDA, encoding="utf-8")
        enviados = []
        anunciador = tunel.AnunciadorDeTunel(
            log, "https://ntfy.sh/x", enviar=lambda a, u: enviados.append(u), registrador=LOG
        )
        assert anunciador.observar() is None
        with log.open("a", encoding="utf-8") as f:
            f.write("INF |  https://fresh-one.trycloudflare.com  |\n")
        assert anunciador.observar() == "https://fresh-one.trycloudflare.com"
        assert enviados == ["https://fresh-one.trycloudflare.com"]

    def test_falha_no_aviso_nao_derruba(self, tmp_path):
        log = tmp_path / "tunel.saida.log"

        def explode(alvo, url):
            raise ConnectionError("sem internet")

        anunciador = tunel.AnunciadorDeTunel(
            log, "https://ntfy.sh/x", enviar=explode, registrador=LOG
        )
        log.write_text(SAIDA, encoding="utf-8")
        assert anunciador.observar() is not None
        assert anunciador.url_atual is not None

    def test_arquivo_truncado_recomeca(self, tmp_path):
        log = tmp_path / "tunel.saida.log"
        anunciador = tunel.AnunciadorDeTunel(log, "", registrador=LOG)
        log.write_text(SAIDA, encoding="utf-8")
        anunciador.observar()
        log.write_text("INF |  https://new-one.trycloudflare.com  |\n", encoding="utf-8")
        assert anunciador.observar() == "https://new-one.trycloudflare.com"
