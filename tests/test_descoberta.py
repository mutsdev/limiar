"""Descoberta da câmera na rede — sem tocar em rede de verdade."""

from __future__ import annotations

from fluxo.operacao import descoberta


class TestRedesParaVarrer:
    def test_deriva_o_barra_24_de_cada_endereco(self):
        redes = descoberta.redes_para_varrer(["10.1.0.47", "192.168.0.5"])
        assert redes == ["10.1.0.0/24", "192.168.0.0/24"]

    def test_dois_enderecos_na_mesma_faixa_viram_uma_rede(self):
        assert descoberta.redes_para_varrer(["10.1.0.47", "10.1.0.90"]) == ["10.1.0.0/24"]

    def test_endereco_invalido_e_ignorado(self):
        assert descoberta.redes_para_varrer(["nao-e-ip", "10.1.0.1"]) == ["10.1.0.0/24"]

    def test_sem_enderecos_devolve_lista_vazia(self):
        assert descoberta.redes_para_varrer([]) == []


class TestVarrer:
    def test_devolve_so_quem_tem_a_porta_aberta(self):
        abertos = {"192.168.1.7", "192.168.1.99"}

        def sonda(ip, porta, timeout):
            return ip in abertos

        achados = descoberta.varrer("192.168.1.0/24", sonda=sonda)
        assert set(achados) == abertos

    def test_nao_testa_rede_nem_broadcast(self):
        vistos = []

        def sonda(ip, porta, timeout):
            vistos.append(ip)
            return False

        descoberta.varrer("192.168.1.0/24", sonda=sonda)
        assert "192.168.1.0" not in vistos
        assert "192.168.1.255" not in vistos
        assert len(vistos) == 254

    def test_rede_sem_ninguem_devolve_vazio(self):
        assert descoberta.varrer("10.0.0.0/29", sonda=lambda *_: False) == []


class TestConfirmar:
    def test_separa_a_camera_de_quem_so_tem_a_porta_aberta(self):
        def confere(url):
            return "10.0.0.5" in url

        assert descoberta.confirmar(["10.0.0.4", "10.0.0.5"], confere=confere) == ["10.0.0.5"]

    def test_recebe_a_url_completa_do_stream(self):
        vistas = []
        descoberta.confirmar(["10.0.0.5"], confere=lambda u: vistas.append(u) or False)
        assert vistas == ["http://10.0.0.5:81/stream"]

    def test_porta_diferente_entra_na_url(self):
        vistas = []
        descoberta.confirmar(
            ["10.0.0.5"], porta=8080, confere=lambda u: vistas.append(u) or False
        )
        assert vistas == ["http://10.0.0.5:8080/stream"]


class TestUrlDoStream:
    def test_formato(self):
        assert descoberta.url_do_stream("10.1.2.3") == "http://10.1.2.3:81/stream"


class TestIpsLocais:
    def test_nao_devolve_loopback_nem_apipa(self):
        # Roda contra a máquina real, mas só verifica o filtro — não a rede.
        for ip in descoberta.ips_locais():
            assert not ip.startswith("127.")
            assert not ip.startswith("169.254.")
