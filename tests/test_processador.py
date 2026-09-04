"""O laço do processador — lacuna, lote, drenagem e o modo contínuo.

Tudo com fontes e rastreadores falsos: o pipeline real de visão não entra
aqui, e os testes rodam no ambiente de núcleo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fluxo.agente import processador
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento
from fluxo.dominio.rastro import Rastro

INSTANTE = datetime(2026, 8, 31, 8, 0, 0, tzinfo=FUSO_LOCAL)


@dataclass(frozen=True, slots=True)
class QuadroFalso:
    indice: int
    instante: datetime
    imagem: object
    apos_lacuna: bool = False


def quadros(n: int, lacuna_em: int | None = None) -> list[QuadroFalso]:
    return [
        QuadroFalso(i, INSTANTE + timedelta(seconds=i), object(), apos_lacuna=(i == lacuna_em))
        for i in range(n)
    ]


def evento(track=1, segundos=0):
    return EventoCruzamento.criar(
        "entrada_a",
        INSTANTE + timedelta(seconds=segundos),
        Direcao.ENTRADA,
        track_id_local=track,
        confianca=0.9,
    )


class FonteLista:
    total_quadros = 0

    def __init__(self, itens):
        self._itens = itens

    def __iter__(self):
        return iter(self._itens)


class RastreadorFalso:
    def __init__(self):
        self.reinicios = 0

    def atualizar(self, imagem):
        return []

    def reiniciar(self):
        self.reinicios += 1


class LinhaFalsa:
    def __init__(self, eventos_por_quadro=None):
        self.eventos_por_quadro = eventos_por_quadro or {}
        self.zeradas = 0
        self.entradas = 0
        self.saidas = 0

    def processar(self, quadro, instante, rastros):
        novos = self.eventos_por_quadro.get(quadro, [])
        self.entradas += sum(1 for e in novos if e.direcao is Direcao.ENTRADA)
        self.saidas += len(novos) - sum(1 for e in novos if e.direcao is Direcao.ENTRADA)
        return novos

    def zerar_rastros(self):
        self.zeradas += 1


class FilaFalsa:
    def __init__(self, tamanho=0):
        self.tamanho = tamanho


class RemetenteFalso:
    def __init__(self, tamanho_fila=0, aceita=True):
        self.fila = FilaFalsa(tamanho_fila)
        self.lotes = []
        self.drenagens = 0
        self.aceita = aceita

    def servico_no_ar(self):
        return False  # pula a drenagem da partida; os testes miram a do laço

    def drenar_fila(self):
        self.drenagens += 1
        drenados = self.fila.tamanho
        self.fila.tamanho = 0
        return drenados

    def enviar(self, eventos):
        self.lotes.append(list(eventos))
        return self.aceita


class TestLacuna:
    def test_quadro_marcado_zera_rastreador_e_linha(self):
        rastreador = RastreadorFalso()
        linha = LinhaFalsa()
        processador.processar(
            FonteLista(quadros(3, lacuna_em=1)), rastreador, linha,
            mostrar_progresso=False,
        )
        assert rastreador.reinicios == 1
        assert linha.zeradas == 1

    def test_sem_marca_nada_e_zerado(self):
        rastreador = RastreadorFalso()
        linha = LinhaFalsa()
        processador.processar(
            FonteLista(quadros(3)), rastreador, linha, mostrar_progresso=False
        )
        assert rastreador.reinicios == 0
        assert linha.zeradas == 0


class TestModoContinuo:
    def test_guardar_eventos_desligado_envia_mas_nao_acumula(self):
        linha = LinhaFalsa({0: [evento(1)]})
        remetente = RemetenteFalso()
        resultado = processador.processar(
            FonteLista(quadros(2)), RastreadorFalso(), linha, remetente,
            mostrar_progresso=False, guardar_eventos=False,
        )
        assert resultado.eventos == []
        assert resultado.entradas == 1
        assert sum(len(lote) for lote in remetente.lotes) == 1

    def test_lote_cheio_drena_a_fila_local(self):
        por_quadro = {i: [evento(track=i, segundos=i)] for i in range(25)}
        remetente = RemetenteFalso(tamanho_fila=3)
        processador.processar(
            FonteLista(quadros(25)), RastreadorFalso(), LinhaFalsa(por_quadro),
            remetente, mostrar_progresso=False,
        )
        assert len(remetente.lotes[0]) == 25
        assert remetente.drenagens == 1
        assert remetente.fila.tamanho == 0

    def test_envio_recusado_nao_drena(self):
        por_quadro = {i: [evento(track=i, segundos=i)] for i in range(25)}
        remetente = RemetenteFalso(tamanho_fila=3, aceita=False)
        processador.processar(
            FonteLista(quadros(25)), RastreadorFalso(), LinhaFalsa(por_quadro),
            remetente, mostrar_progresso=False,
        )
        assert remetente.drenagens == 0
        assert remetente.fila.tamanho == 3


class TestZerarRastrosReal:
    def test_esquece_estados_e_preserva_contadores(self):
        linha = LinhaDeContagem("entrada_a", a=(50.0, 0.0), b=(50.0, 100.0))
        rastro = Rastro(id_local=1, caixa=(10.0, 10.0, 20.0, 30.0), confianca=0.9)
        linha.processar(0, INSTANTE, [rastro])
        assert linha.rastros_ativos == 1

        linha.entradas = 3
        linha.saidas = 2
        linha.zerar_rastros()

        assert linha.rastros_ativos == 0
        assert linha.entradas == 3
        assert linha.saidas == 2


class IdentidadeFalsa:
    def __init__(self):
        self.observados = []
        self.fechadas = 0

    def observar(self, quadro, rastros, novos, avisar=None):
        self.observados.append((quadro.indice, list(novos)))
        return []

    def fechar(self, avisar=None):
        self.fechadas += 1
        return []

    def etiquetas(self):
        return {}

    def placar(self):
        return ""


class TestIdentidade:
    """A Etapa 2 entra por um parâmetro opcional; sem ele, nada muda."""

    def test_observa_todo_quadro_com_os_eventos_e_fecha_no_fim(self):
        identidade = IdentidadeFalsa()
        linha = LinhaFalsa({1: [evento(1, segundos=1)]})
        processador.processar(
            FonteLista(quadros(3)), RastreadorFalso(), linha,
            mostrar_progresso=False, identidade=identidade,
        )
        assert [i for i, _ in identidade.observados] == [0, 1, 2]
        assert [len(n) for _, n in identidade.observados] == [0, 1, 0]
        assert identidade.fechadas == 1

    def test_sem_identidade_o_resultado_e_o_mesmo(self):
        linha = LinhaFalsa({1: [evento(1, segundos=1)]})
        sem = processador.processar(
            FonteLista(quadros(3)), RastreadorFalso(), linha, mostrar_progresso=False,
        )
        linha = LinhaFalsa({1: [evento(1, segundos=1)]})
        com = processador.processar(
            FonteLista(quadros(3)), RastreadorFalso(), linha, mostrar_progresso=False,
            identidade=IdentidadeFalsa(),
        )
        assert (sem.quadros, sem.entradas, len(sem.eventos)) == (
            com.quadros, com.entradas, len(com.eventos)
        )
