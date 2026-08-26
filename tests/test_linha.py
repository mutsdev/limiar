"""A linha de contagem alimentada com trajetórias inventadas.

Nenhum vídeo, nenhum modelo. Cada teste descreve um comportamento real de
porta — quem atravessa, quem hesita, quem volta — e trava o que o contador
deve fazer com ele.
"""

from datetime import datetime, timedelta

import pytest

from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.dominio.rastro import Rastro

INICIO = datetime(2026, 8, 25, 14, 0, 0, tzinfo=FUSO_LOCAL)
FPS = 25

# Linha vertical. Com a=(450,30) e b=(450,240), o lado direito dá -1, então
# "dentro" é a direita — como a câmera montada olhando para a rua.
A = (450.0, 30.0)
B = (450.0, 240.0)
LADO_DENTRO = -1


def nova_linha(**kwargs) -> LinhaDeContagem:
    padrao = dict(
        camera_id="entrada_a",
        a=A,
        b=B,
        lado_dentro=LADO_DENTRO,
        idade_minima_track=3,
        janela_suavizacao=3,
        zona_morta_px=15.0,
        cooldown_segundos=1.5,
    )
    padrao.update(kwargs)
    return LinhaDeContagem(**padrao)


def rastro_em(x: float, y: float, track: int = 1, conf: float = 0.9) -> Rastro:
    """Caixa cuja base cai exatamente em (x, y)."""
    return Rastro(id_local=track, caixa=(x - 20, y - 100, x + 20, y), confianca=conf)


def percorrer(linha, xs, y=135.0, track=1, quadro0=0, instante0=INICIO):
    """Passa a pessoa pelas posições `xs` e devolve os eventos gerados."""
    eventos = []
    for i, x in enumerate(xs):
        instante = instante0 + timedelta(seconds=(quadro0 + i) / FPS)
        eventos += linha.processar(quadro0 + i, instante, [rastro_em(x, y, track)])
    return eventos


class TestTravessiaLimpa:
    def test_da_esquerda_para_a_direita_e_entrada(self):
        linha = nova_linha()
        eventos = percorrer(linha, [300, 340, 380, 420, 480, 520, 560, 600])
        assert len(eventos) == 1
        assert eventos[0].direcao is Direcao.ENTRADA
        assert eventos[0].camera_id == "entrada_a"
        assert linha.entradas == 1 and linha.saidas == 0

    def test_da_direita_para_a_esquerda_e_saida(self):
        linha = nova_linha()
        eventos = percorrer(linha, [600, 560, 520, 480, 420, 380, 340, 300])
        assert len(eventos) == 1
        assert eventos[0].direcao is Direcao.SAIDA
        assert linha.saidas == 1 and linha.entradas == 0

    def test_o_evento_leva_o_track_e_a_confianca(self):
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 500, 550], track=77)
        assert eventos[0].track_id_local == 77
        assert eventos[0].confianca == pytest.approx(0.9)

    def test_atravessar_e_seguir_nao_conta_duas_vezes(self):
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 500, 550, 600, 650, 700, 750])
        assert len(eventos) == 1


class TestNaoDeveContar:
    def test_quem_chega_perto_e_volta_do_mesmo_lado(self):
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 430, 400, 350, 300])
        assert eventos == []

    def test_quem_anda_paralelo_a_linha(self):
        linha = nova_linha()
        eventos = []
        for i, y in enumerate([40, 70, 100, 130, 160, 190, 220]):
            instante = INICIO + timedelta(seconds=i / FPS)
            eventos += linha.processar(i, instante, [rastro_em(300.0, y)])
        assert eventos == []

    def test_quem_cruza_a_reta_fora_do_segmento(self):
        """Passa longe da porta, abaixo do fim da linha desenhada.

        Sem a checagem de segmento — só o lado da reta infinita — isto seria
        contado, e a contagem incluiria quem nem chegou perto da entrada.
        """
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 500, 550, 600], y=800.0)
        assert eventos == []

    def test_track_novo_demais(self):
        """Dois quadros não bastam: elimina detecção instantânea."""
        linha = nova_linha(idade_minima_track=3)
        eventos = percorrer(linha, [300, 600])
        assert eventos == []

    def test_track_que_nasce_ja_do_outro_lado(self):
        """Aparece pela primeira vez depois da linha, sem histórico.

        O cruzamento se perde. É uma limitação conhecida e declarada — a
        avaliação mede o quanto ela custa.
        """
        linha = nova_linha()
        eventos = percorrer(linha, [600, 620, 640, 660, 680])
        assert eventos == []


class TestHistereseECooldown:
    def test_tremulacao_em_cima_da_linha_nao_dispara(self):
        """A caixa oscila dentro da zona morta: nada é confirmado."""
        linha = nova_linha(zona_morta_px=15.0)
        xs = [300, 350, 400, 440, 448, 452, 445, 455, 448, 452, 447, 453]
        eventos = percorrer(linha, xs)
        assert eventos == []

    def test_oscilacao_media_e_absorvida_pela_suavizacao(self):
        """Vai-e-vem de ±30 px em torno da linha: nenhum evento.

        A média móvel reduz a oscilação a ±10 px, que cabe dentro da zona
        morta. Duas defesas em série — suavizar e depois exigir afastamento —
        e a hesitação na porta morre antes de chegar ao cooldown.
        """
        linha = nova_linha(zona_morta_px=15.0)
        eventos = percorrer(linha, [300, 350, 400, 480, 420, 480, 420, 480, 420, 480])
        assert eventos == []

    def test_oscilacao_ampla_e_rapida_conta_uma_vez_so(self):
        """Vai-e-vem de ±110 px em 0,3 s: grande demais para a suavização.

        Aqui quem segura é o cooldown, e ele reduz a série a um evento. A
        escolha é deliberada: quem entra e sai de verdade em menos de 1,5 s é
        raro; quem hesita na porta é comum.
        """
        linha = nova_linha(cooldown_segundos=1.5)
        eventos = percorrer(linha, [300, 360, 420, 560, 340, 560, 340, 560, 340, 560])
        assert len(eventos) == 1

    def test_ida_e_volta_lenta_conta_as_duas(self):
        """Entrou, ficou dentro, e saiu depois — dois eventos legítimos."""
        linha = nova_linha(cooldown_segundos=1.5)
        eventos = percorrer(linha, [300, 350, 400, 480, 520, 560])
        assert len(eventos) == 1
        # Cem quadros depois (4 s), bem além do cooldown.
        eventos += percorrer(linha, [560, 520, 480, 420, 380, 340], quadro0=100)
        assert len(eventos) == 2
        assert eventos[0].direcao is Direcao.ENTRADA
        assert eventos[1].direcao is Direcao.SAIDA

    def test_zona_morta_maior_exige_afastamento_maior(self):
        linha = nova_linha(zona_morta_px=100.0)
        # Cruza, mas nunca se afasta 100 px da linha: não é confirmado.
        assert percorrer(linha, [400, 410, 420, 480, 490, 500]) == []


class TestVariasPessoas:
    def test_duas_pessoas_simultaneas_geram_dois_eventos(self):
        linha = nova_linha()
        eventos = []
        for i, (xa, xb) in enumerate(
            [(300, 600), (350, 560), (400, 520), (500, 420), (550, 380), (600, 340)]
        ):
            instante = INICIO + timedelta(seconds=i / FPS)
            eventos += linha.processar(
                i, instante, [rastro_em(xa, 135, track=1), rastro_em(xb, 135, track=2)]
            )
        assert len(eventos) == 2
        assert {e.direcao for e in eventos} == {Direcao.ENTRADA, Direcao.SAIDA}
        assert linha.entradas == 1 and linha.saidas == 1

    def test_cada_track_tem_seu_proprio_cooldown(self):
        """O cooldown de uma pessoa não pode silenciar a passagem de outra."""
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 500, 550], track=1)
        eventos += percorrer(linha, [300, 350, 400, 500, 550], track=2)
        assert len(eventos) == 2

    def test_chaves_de_evento_sao_distintas(self):
        linha = nova_linha()
        eventos = percorrer(linha, [300, 350, 400, 500, 550], track=1)
        eventos += percorrer(linha, [600, 560, 520, 420, 380], track=2)
        assert len({e.id_evento for e in eventos}) == len(eventos)


class TestMemoria:
    def test_track_sumido_e_esquecido(self):
        linha = nova_linha(quadros_ate_esquecer=10)
        percorrer(linha, [300, 350, 400], track=1)
        assert linha.rastros_ativos == 1
        # Passam 50 quadros só com outra pessoa em cena.
        percorrer(linha, [700] * 5, track=2, quadro0=50)
        assert linha.rastros_ativos == 1  # sobrou só o track 2

    def test_quadro_sem_ninguem_nao_quebra(self):
        linha = nova_linha()
        assert linha.processar(0, INICIO, []) == []
        assert linha.rastros_ativos == 0


class TestConfiguracao:
    def test_linha_nao_calibrada_da_erro_util(self):
        with pytest.raises(ValueError, match="calibrar_linha"):
            LinhaDeContagem.de_config("entrada_a", {"linha": None}, {})

    def test_monta_a_partir_dos_yaml(self):
        linha = LinhaDeContagem.de_config(
            "entrada_b",
            {"linha": [10, 20, 30, 40], "lado_dentro": -1},
            {"contagem": {"zona_morta_px": 8, "cooldown_segundos": 2.0}},
        )
        assert linha.camera_id == "entrada_b"
        assert linha.a == (10.0, 20.0) and linha.b == (30.0, 40.0)
        assert linha.lado_dentro == -1
        assert linha.zona_morta_px == 8.0
        assert linha.cooldown_segundos == 2.0
