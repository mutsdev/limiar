"""Quadro ao vivo: um arquivo só, escrito inteiro, no ritmo certo."""

from __future__ import annotations

import os

from fluxo.visao.quadro_vivo import PublicadorDeQuadro, idade_do_quadro


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _publicador(tmp_path, relogio, **kw):
    return PublicadorDeQuadro(
        tmp_path / "quadros" / "entrada_real.jpg",
        codificar=lambda imagem: f"JPEG:{imagem}".encode(),
        relogio=relogio, **kw,
    )


class TestPublicar:
    def test_grava_inteiro_e_sobrescreve(self, tmp_path):
        relogio = Relogio()
        pub = _publicador(tmp_path, relogio, intervalo_s=0.2)
        assert pub.publicar("a")
        assert pub.caminho.read_bytes() == b"JPEG:a"
        relogio.t = 0.5
        assert pub.publicar("b")
        assert pub.caminho.read_bytes() == b"JPEG:b"
        assert not pub.caminho.with_suffix(".tmp").exists()
        assert pub.publicados == 2

    def test_respeita_o_intervalo(self, tmp_path):
        relogio = Relogio()
        pub = _publicador(tmp_path, relogio, intervalo_s=0.2)
        assert pub.publicar("a")
        relogio.t = 0.1
        assert not pub.publicar("b")
        assert pub.caminho.read_bytes() == b"JPEG:a"

    def test_falha_de_codificacao_nao_derruba(self, tmp_path):
        def quebra(imagem):
            raise ValueError("imagem vazia")

        pub = PublicadorDeQuadro(tmp_path / "x.jpg", codificar=quebra, relogio=Relogio())
        assert not pub.publicar("a")
        assert pub.falhas == 1


class TestIdade:
    def test_idade_e_ausencia(self, tmp_path):
        arquivo = tmp_path / "entrada_real.jpg"
        assert idade_do_quadro(arquivo) is None
        arquivo.write_bytes(b"x")
        os.utime(arquivo, (1000.0, 1000.0))
        assert idade_do_quadro(arquivo, agora=1012.0) == 12.0
