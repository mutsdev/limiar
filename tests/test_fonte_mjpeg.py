"""Separação dos quadros do multipart MJPEG.

Função pura: nenhum teste aqui abre rede ou usa OpenCV. Os bytes imitam o que
o CameraWebServer do ESP32 manda de verdade.
"""

from __future__ import annotations

import pytest

from fluxo.visao.fonte_mjpeg import LIMITE_BUFFER, separar_quadros

DELIMITADOR = b"\r\n--123456789000000000000987654321\r\n"


def parte(corpo: bytes, com_timestamp: bool = True) -> bytes:
    """Uma parte do multipart, no formato exato do firmware.

    `X-Timestamp` vem DEPOIS do `Content-Length` (app_httpd.cpp:98). Foi o que
    quebrou a primeira versão do separador, então é o padrão aqui.
    """
    extra = b"X-Timestamp: 1756750000.123456\r\n" if com_timestamp else b""
    return (
        DELIMITADOR
        + b"Content-Type: image/jpeg\r\nContent-Length: "
        + str(len(corpo)).encode()
        + b"\r\n"
        + extra
        + b"\r\n"
        + corpo
    )


def em_pedacos(dados: bytes, tamanho: int) -> list[bytes]:
    return [dados[i:i + tamanho] for i in range(0, len(dados), tamanho)]


class TestSepararQuadros:
    def test_extrai_os_quadros_na_ordem(self):
        corrente = parte(b"AAAA") + parte(b"BBBBBB") + parte(b"CC")
        assert list(separar_quadros([corrente])) == [b"AAAA", b"BBBBBB", b"CC"]

    @pytest.mark.parametrize("tamanho", [1, 3, 7, 64, 4096])
    def test_independe_de_onde_o_pedaco_corta(self, tamanho):
        """O TCP entrega em pedaços arbitrários — inclusive no meio do cabeçalho."""
        corrente = parte(b"12345") + parte(b"67890")
        assert list(separar_quadros(em_pedacos(corrente, tamanho))) == [b"12345", b"67890"]

    def test_quadro_incompleto_no_fim_nao_e_entregue(self):
        """Conexão cortada no meio de um JPEG: melhor nada que meio quadro."""
        corrente = parte(b"COMPLETO") + DELIMITADOR + b"Content-Length: 99\r\n\r\nso um pedaco"
        assert list(separar_quadros([corrente])) == [b"COMPLETO"]

    def test_delimitador_dentro_do_jpeg_nao_confunde(self):
        """Dado binário contém qualquer sequência: por isso se usa o tamanho."""
        corpo = b"antes" + DELIMITADOR + b"depois"
        assert list(separar_quadros([parte(corpo)])) == [corpo]

    def test_cabecalho_sem_corpo_nao_estoura_a_memoria(self):
        lixo = [b"x" * 65536] * ((LIMITE_BUFFER // 65536) + 2)
        with pytest.raises(ValueError, match="não é MJPEG"):
            list(separar_quadros(lixo))

    def test_corrente_vazia_devolve_nada(self):
        assert list(separar_quadros([])) == []

    def test_funciona_com_e_sem_cabecalho_extra(self):
        """Regressão: o X-Timestamp depois do Content-Length zerava a leitura."""
        com = parte(b"COM", com_timestamp=True)
        sem = parte(b"SEM", com_timestamp=False)
        assert list(separar_quadros([com + sem])) == [b"COM", b"SEM"]

    def test_content_length_com_caixa_diferente(self):
        corrente = DELIMITADOR + b"content-length: 3\r\n\r\nabc"
        assert list(separar_quadros([corrente])) == [b"abc"]
