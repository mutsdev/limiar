"""Pulso de vida: bate com estrangulamento, e a leitura julga pela idade."""

from __future__ import annotations

import os

from fluxo.operacao.pulso import Pulso, pulso_recente


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
