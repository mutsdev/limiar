"""Escolha do interpretador e nome de câmera a partir do arquivo."""

import os

import pytest

from fluxo import ambiente


class TestIdDeCamera:
    @pytest.mark.parametrize(
        "caminho,esperado",
        [
            (r"C:\Users\joaop\Downloads\01_camera_elevada.mp4", "01_camera_elevada"),
            ("porta.mp4", "porta"),
            ("/home/x/Videos/Porta Principal.MP4", "porta_principal"),
            ("Porta - 27/08.mkv", "08"),          # o separador vira parte do caminho
            ("entrada  lateral.mp4", "entrada_lateral"),
            ("Câmera Frontal.mp4", "camera_frontal"),   # acento vira ASCII
        ],
    )
    def test_deriva(self, caminho, esperado):
        assert ambiente.id_de_camera(caminho) == esperado

    def test_nunca_devolve_vazio(self):
        """Um nome só de pontuação ainda precisa virar um id utilizável."""
        assert ambiente.id_de_camera("---.mp4") == "camera"

    def test_limita_o_tamanho(self):
        assert len(ambiente.id_de_camera("a" * 200 + ".mp4")) <= 48

    def test_e_estavel(self):
        a = ambiente.id_de_camera(r"C:\x\Porta.mp4")
        b = ambiente.id_de_camera(r"C:\outro\lugar\Porta.MP4")
        assert a == b == "porta"


class TestEscolhaDoAmbiente:
    def _montar(self, raiz, com_cv2: bool):
        libs = raiz / ("Lib/site-packages" if os.name == "nt" else "lib")
        libs.mkdir(parents=True)
        exe = raiz / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("", encoding="utf-8")
        if com_cv2:
            (libs / "cv2").mkdir()
        return raiz

    def test_variavel_de_ambiente_manda(self, tmp_path, monkeypatch):
        venv = self._montar(tmp_path / "meu", com_cv2=True)
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venv))
        assert ambiente.ambiente_do_projeto() == venv

    def test_variavel_apontando_para_nada_devolve_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "inexistente"))
        assert ambiente.ambiente_do_projeto() is None

    def test_prefere_o_que_tem_visao(self, tmp_path, monkeypatch):
        """Um ambiente só com o núcleo roda os testes, mas não abre vídeo.

        Escolhê-lo para um script de visão daria ModuleNotFoundError depois de
        trocar de interpretador — erro confuso, longe da causa. Aconteceu.
        """
        monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
        so_nucleo = self._montar(tmp_path / "nucleo", com_cv2=False)
        com_visao = self._montar(tmp_path / "visao", com_cv2=True)
        monkeypatch.setattr(ambiente, "CANDIDATOS", (so_nucleo, com_visao))

        assert ambiente.ambiente_do_projeto(exigir_visao=True) == com_visao
        assert ambiente.ambiente_do_projeto(exigir_visao=False) == so_nucleo

    def test_sem_visao_em_lugar_nenhum_usa_o_primeiro(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
        a = self._montar(tmp_path / "a", com_cv2=False)
        b = self._montar(tmp_path / "b", com_cv2=False)
        monkeypatch.setattr(ambiente, "CANDIDATOS", (a, b))
        assert ambiente.ambiente_do_projeto(exigir_visao=True) == a

    def test_nenhum_ambiente_devolve_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
        monkeypatch.setattr(ambiente, "CANDIDATOS", (tmp_path / "nada",))
        assert ambiente.ambiente_do_projeto() is None


class TestGarantirVenv:
    def test_marca_de_reentrada_impede_laco(self, monkeypatch):
        """Sem ela, um ambiente quebrado se reexecutaria para sempre."""
        monkeypatch.setenv("_LIMIAR_REEXEC", "1")

        def nao_deveria(*_a, **_k):
            raise AssertionError("não deveria ter reexecutado")

        monkeypatch.setattr(os, "execv", nao_deveria)
        ambiente.garantir_venv()

    def test_sem_ambiente_nao_faz_nada(self, tmp_path, monkeypatch):
        monkeypatch.delenv("_LIMIAR_REEXEC", raising=False)
        monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
        monkeypatch.setattr(ambiente, "CANDIDATOS", (tmp_path / "nada",))

        def nao_deveria(*_a, **_k):
            raise AssertionError("não deveria ter reexecutado")

        monkeypatch.setattr(os, "execv", nao_deveria)
        ambiente.garantir_venv()
