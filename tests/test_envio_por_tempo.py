"""O lote de eventos sobe por tempo, não só quando enche.

Com pouco movimento, 25 travessias podem levar uma tarde. Nesse meio-tempo o
painel não vê nada e, se o agente morrer, tudo o que estava na memória morre
junto. O supervisor relança o processo; a memória não volta.
"""

from datetime import datetime, timedelta

from fluxo.agente import processador
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento

INSTANTE = datetime(2026, 9, 3, 15, 0, 0, tzinfo=FUSO_LOCAL)


class Quadro:
    def __init__(self, i):
        self.indice = i
        self.instante = INSTANTE + timedelta(seconds=i)
        self.imagem = object()
        self.apos_lacuna = False


class Fonte:
    total_quadros = 0

    def __init__(self, n):
        self.n = n

    def __iter__(self):
        return (Quadro(i) for i in range(self.n))


class Rastreador:
    def atualizar(self, imagem):
        return []

    def reiniciar(self):
        pass


class Linha:
    entradas = 0
    saidas = 0

    def __init__(self, quando):
        self.quando = quando

    def processar(self, quadro, instante, rastros):
        if quadro in self.quando:
            return [EventoCruzamento.criar(
                "entrada_a", instante, Direcao.ENTRADA, track_id_local=quadro,
            )]
        return []

    def zerar_rastros(self):
        pass


class Fila:
    tamanho = 0


class Remetente:
    def __init__(self):
        self.fila = Fila()
        self.lotes = []  # (quadro em que saiu, tamanho)

    def servico_no_ar(self):
        return False

    def drenar_fila(self):
        return 0

    def enviar(self, eventos):
        self.lotes.append(list(eventos))
        return True


def test_um_evento_sobe_depois_do_intervalo_e_nao_so_no_fim(monkeypatch):
    monkeypatch.setattr(processador, "INTERVALO_ENVIO_S", 30.0)
    remetente = Remetente()
    processador.processar(
        Fonte(100), Rastreador(), Linha({0}), remetente, mostrar_progresso=False
    )
    # Um só evento, mas ele não esperou os 25: subiu sozinho quando venceu.
    assert [len(lote) for lote in remetente.lotes] == [1]
    assert remetente.lotes[0][0].track_id_local == 0


def test_lote_cheio_continua_subindo_na_hora(monkeypatch):
    monkeypatch.setattr(processador, "INTERVALO_ENVIO_S", 3600.0)
    remetente = Remetente()
    processador.processar(
        Fonte(30), Rastreador(), Linha(set(range(25))), remetente, mostrar_progresso=False
    )
    assert len(remetente.lotes[0]) == 25


def test_abaixo_do_intervalo_espera(monkeypatch):
    monkeypatch.setattr(processador, "INTERVALO_ENVIO_S", 3600.0)
    remetente = Remetente()
    processador.processar(
        Fonte(10), Rastreador(), Linha({0, 5}), remetente, mostrar_progresso=False
    )
    # Só o envio final, depois do laço: os dois juntos.
    assert [len(lote) for lote in remetente.lotes] == [2]
