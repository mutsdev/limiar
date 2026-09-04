"""Logging com rotação — idempotência e rotação diária."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from fluxo import registro


def limpar(nome: str) -> None:
    logger = logging.getLogger(nome)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


class TestConfigurar:
    def test_escreve_no_arquivo(self, tmp_path):
        arquivo = tmp_path / "agente.log"
        logger = registro.configurar("teste-escreve", arquivo, console=False)
        try:
            logger.info("linha de teste")
            for h in logger.handlers:
                h.flush()
            assert "linha de teste" in arquivo.read_text(encoding="utf-8")
        finally:
            limpar("teste-escreve")

    def test_chamada_repetida_nao_duplica_handlers(self, tmp_path):
        arquivo = tmp_path / "a.log"
        try:
            registro.configurar("teste-idem", arquivo)
            logger = registro.configurar("teste-idem", arquivo)
            de_arquivo = [
                h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)
            ]
            de_console = [
                h for h in logger.handlers if not isinstance(h, TimedRotatingFileHandler)
            ]
            assert len(de_arquivo) == 1
            assert len(de_console) == 1
        finally:
            limpar("teste-idem")

    def test_sem_escrever_nao_cria_arquivo(self, tmp_path):
        """delay=True: logger configurado por via das dúvidas não deixa lixo."""
        arquivo = tmp_path / "vazio.log"
        try:
            registro.configurar("teste-vazio", arquivo, console=False)
            assert not arquivo.exists()
        finally:
            limpar("teste-vazio")

    def test_rotacao_preserva_o_conteudo_antigo(self, tmp_path):
        arquivo = tmp_path / "rotativo.log"
        logger = registro.configurar("teste-rotacao", arquivo, console=False)
        try:
            logger.info("antes da virada")
            handler = next(
                h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)
            )
            handler.doRollover()
            logger.info("depois da virada")
            for h in logger.handlers:
                h.flush()

            assert "depois da virada" in arquivo.read_text(encoding="utf-8")
            rotacionados = list(tmp_path.glob("rotativo.log.*"))
            assert len(rotacionados) == 1
            assert "antes da virada" in rotacionados[0].read_text(encoding="utf-8")
        finally:
            limpar("teste-rotacao")
