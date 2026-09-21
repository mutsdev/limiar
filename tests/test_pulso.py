"""Pulso de vida: bate com estrangulamento, e a leitura julga pela idade."""

from __future__ import annotations

import os

from fluxo.operacao.pulso import (
    Pulso,
    arquivo_de_quadro,
    arquivo_do_agente,
    pulso_recente,
)


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestBater:
    def test_cria_o_arquivo_e_estrangula(self, tmp_path):
        relogio = Relogio()
        pulso = Pulso(tmp_path / "sub" / "agente.pulso", a_cada_s=5.0, relogio=relogio)
        pulso.bater()
        assert pulso.arquivo.exists()
        relogio.t = 4.0
        pulso.bater()
        assert pulso.batidas == 1
        relogio.t = 5.0
        pulso.bater()
        assert pulso.batidas == 2


class TestRecente:
    def test_julga_pela_idade_do_arquivo(self, tmp_path):
        arquivo = tmp_path / "agente.pulso"
        arquivo.touch()
        os.utime(arquivo, (1000.0, 1000.0))
        assert pulso_recente(arquivo, maximo_s=180.0, agora=1100.0)
        assert not pulso_recente(arquivo, maximo_s=180.0, agora=1181.0)

    def test_sem_arquivo_e_nao(self, tmp_path):
        assert not pulso_recente(tmp_path / "nada.pulso", maximo_s=180.0)


class TestArquivos:
    def test_pulso_e_quadro_sao_arquivos_diferentes(self):
        # Duas perguntas diferentes: "o processo está preso?" e "a câmera está
        # entregando?". Compartilhar o arquivo apagaria a distinção.
        assert arquivo_do_agente("entrada_real") != arquivo_de_quadro("entrada_real")
        assert arquivo_do_agente("entrada_real").name == "agente_entrada_real.pulso"
        assert arquivo_de_quadro("entrada_real").name == "agente_entrada_real.quadro"

    def test_batem_de_forma_independente(self, tmp_path):
        relogio = Relogio()
        laco = Pulso(tmp_path / "a.pulso", relogio=relogio)
        quadro = Pulso(tmp_path / "a.quadro", relogio=relogio)
        laco.bater()
        assert laco.arquivo.exists()
        # Câmera fora do ar: o laço bate, o quadro não. É este o estado que
        # nenhuma camada de supervisão enxergava.
        assert not quadro.arquivo.exists()
