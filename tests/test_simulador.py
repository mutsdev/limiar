from datetime import date

from fluxo.dominio.evento import Direcao, Origem
from fluxo.simulacao import gerador

DIA = date(2026, 8, 25)  # terça-feira


class TestGerarDia:
    def test_marca_tudo_como_sintetico(self):
        eventos = gerador.gerar_dia(DIA, pessoas=100, semente=1)
        assert all(e.origem is Origem.SINTETICO for e in eventos)

    def test_chaves_sao_unicas(self):
        eventos = gerador.gerar_dia(DIA, pessoas=300, semente=1)
        assert len({e.id_evento for e in eventos}) == len(eventos)

    def test_balanco_do_dia_fecha(self):
        """Cada pessoa entra e sai. Se o balanço não fechar, a curva de
        ocupação que o painel desenha estaria errada."""
        eventos = gerador.gerar_dia(DIA, pessoas=500, semente=7)
        entradas = sum(e.direcao is Direcao.ENTRADA for e in eventos)
        saidas = sum(e.direcao is Direcao.SAIDA for e in eventos)
        assert entradas == saidas

    def test_sai_ordenado_no_tempo(self):
        eventos = gerador.gerar_dia(DIA, pessoas=200, semente=3)
        assert eventos == sorted(eventos, key=lambda e: e.instante)

    def test_usa_as_duas_cameras(self):
        eventos = gerador.gerar_dia(DIA, pessoas=300, semente=5)
        assert {e.camera_id for e in eventos} == {"entrada_a", "entrada_b"}

    def test_a_semente_torna_o_dia_reproduzivel(self):
        a = gerador.gerar_dia(DIA, pessoas=150, semente=99)
        b = gerador.gerar_dia(DIA, pessoas=150, semente=99)
        assert [e.id_evento for e in a] == [e.id_evento for e in b]
        assert [e.instante for e in a] == [e.instante for e in b]

    def test_tudo_cai_no_dia_pedido(self):
        eventos = gerador.gerar_dia(DIA, pessoas=400, semente=11)
        assert {e.data_ref for e in eventos} == {DIA}

    def test_a_curva_tem_pico_de_manha_e_no_comeco_da_noite(self):
        eventos = gerador.gerar_dia(DIA, pessoas=2000, semente=13)
        por_hora: dict[int, int] = {}
        for e in eventos:
            if e.direcao is Direcao.ENTRADA:
                por_hora[e.instante.hour] = por_hora.get(e.instante.hour, 0) + 1
        # As 7h e as 18h devem superar as 15h, que é vale na curva.
        assert por_hora[7] > por_hora[15]
        assert por_hora[18] > por_hora[15]


class TestGerarPeriodo:
    def test_pula_domingo(self):
        # 24/08/2026 é segunda; sete dias cobrem um domingo (30/08).
        eventos = gerador.gerar_periodo(date(2026, 8, 24), dias=7, semente=1)
        assert all(e.data_ref.weekday() != 6 for e in eventos)

    def test_sabado_e_bem_mais_fraco_que_terca(self):
        eventos = gerador.gerar_periodo(date(2026, 8, 24), dias=7, semente=1)
        por_dia: dict[date, int] = {}
        for e in eventos:
            por_dia[e.data_ref] = por_dia.get(e.data_ref, 0) + 1
        terca, sabado = date(2026, 8, 25), date(2026, 8, 29)
        assert por_dia[sabado] < por_dia[terca] * 0.5

    def test_cobre_o_numero_de_dias_pedido(self):
        eventos = gerador.gerar_periodo(date(2026, 8, 24), dias=6, semente=2)
        assert len({e.data_ref for e in eventos}) == 6
