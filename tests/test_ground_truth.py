"""Carregamento da referência de avaliação."""

from datetime import datetime

import pytest

from fluxo.avaliacao import ground_truth as gt
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao

INICIO = datetime(2026, 8, 25, 14, 0, 0, tzinfo=FUSO_LOCAL)


# --------------------------------------------------------------------------
# CSV da contagem manual
# --------------------------------------------------------------------------


class TestCarregarCsv:
    def test_le_com_cabecalho(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("minuto,entradas,saidas\n0,12,3\n1,9,5\n", encoding="utf-8")

        c = gt.carregar_csv(arquivo)
        assert c.entradas == 21
        assert c.saidas == 8
        assert c.por_minuto[1] == (9, 5)

    def test_le_sem_cabecalho(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("0,4,1\n1,2,2\n", encoding="utf-8")
        assert gt.carregar_csv(arquivo).entradas == 6

    def test_ignora_comentario_e_linha_em_branco(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("# contado por duas pessoas\n\n0,4,1\n\n1,2,2\n", encoding="utf-8")
        assert len(gt.carregar_csv(arquivo).por_minuto) == 2

    def test_series_por_minuto_para_o_mae(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("0,4,1\n1,2,2\n", encoding="utf-8")
        c = gt.carregar_csv(arquivo)
        assert c.entradas_por_minuto() == {0: 4, 1: 2}
        assert c.saidas_por_minuto() == {0: 1, 1: 2}

    def test_arquivo_inexistente_da_erro_util(self, tmp_path):
        with pytest.raises(gt.GroundTruthInvalido, match="não encontrado"):
            gt.carregar_csv(tmp_path / "nao-existe.csv")

    def test_campos_de_menos_apontam_a_linha(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("0,4,1\n1,2\n", encoding="utf-8")
        with pytest.raises(gt.GroundTruthInvalido, match=":2"):
            gt.carregar_csv(arquivo)

    def test_valor_nao_numerico_e_recusado(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("0,quatro,1\n", encoding="utf-8")
        with pytest.raises(gt.GroundTruthInvalido, match="numérico"):
            gt.carregar_csv(arquivo)

    def test_minuto_repetido_e_recusado(self, tmp_path):
        """Duas linhas para o mesmo minuto quase sempre são erro de digitação,
        e aceitar a última em silêncio esconderia contagem perdida."""
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("0,4,1\n0,9,9\n", encoding="utf-8")
        with pytest.raises(gt.GroundTruthInvalido, match="repete o minuto"):
            gt.carregar_csv(arquivo)

    def test_arquivo_so_com_cabecalho_e_recusado(self, tmp_path):
        arquivo = tmp_path / "gt.csv"
        arquivo.write_text("minuto,entradas,saidas\n", encoding="utf-8")
        with pytest.raises(gt.GroundTruthInvalido, match="nenhuma linha"):
            gt.carregar_csv(arquivo)


# --------------------------------------------------------------------------
# MOTChallenge
# --------------------------------------------------------------------------


def montar_sequencia(tmp_path, linhas_gt, seqinfo=True, nome="MOT17-99"):
    pasta = tmp_path / nome
    (pasta / "gt").mkdir(parents=True)
    (pasta / "gt" / "gt.txt").write_text("\n".join(linhas_gt) + "\n", encoding="utf-8")
    if seqinfo:
        (pasta / "seqinfo.ini").write_text(
            "[Sequence]\nname=" + nome + "\nimDir=img1\nframeRate=30\n"
            "seqLength=100\nimWidth=1920\nimHeight=1080\nimExt=.jpg\n",
            encoding="utf-8",
        )
    return pasta


class TestCarregarMot:
    def test_le_metadados_do_seqinfo(self, tmp_path):
        pasta = montar_sequencia(tmp_path, ["1,1,100,200,50,150,1,1,1.0"])
        s = gt.carregar_mot(pasta)
        assert s.nome == "MOT17-99"
        assert s.fps == 30.0
        assert s.quadros == 100
        assert (s.largura, s.altura) == (1920, 1080)

    def test_converte_para_caixa_do_dominio(self, tmp_path):
        pasta = montar_sequencia(tmp_path, ["1,7,100,200,50,150,1,1,1.0"])
        rastro = gt.carregar_mot(pasta).rastros(1)[0]
        assert rastro.id_local == 7
        assert rastro.caixa == (100.0, 200.0, 150.0, 350.0)
        # O ponto do pé precisa bater com o que o pipeline usa.
        assert rastro.ponto_base == (125.0, 350.0)

    def test_descarta_regiao_marcada_para_ignorar(self, tmp_path):
        """conf=0 é o anotador dizendo explicitamente para desconsiderar."""
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,1.0",
            "1,2,300,200,50,150,0,1,1.0",
        ])
        assert [r.id_local for r in gt.carregar_mot(pasta).rastros(1)] == [1]

    def test_descarta_quem_nao_e_pedestre(self, tmp_path):
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,1.0",
            "1,2,300,200,50,150,1,3,1.0",   # classe 3: carro
            "1,3,500,200,50,150,1,7,1.0",   # classe 7: pessoa sentada
        ])
        assert [r.id_local for r in gt.carregar_mot(pasta).rastros(1)] == [1]

    def test_filtro_de_visibilidade_e_opcional(self, tmp_path):
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,0.9",
            "1,2,300,200,50,150,1,1,0.1",
        ])
        assert len(gt.carregar_mot(pasta).rastros(1)) == 2
        s = gt.carregar_mot(pasta, visibilidade_minima=0.5)
        assert [r.id_local for r in s.rastros(1)] == [1]

    def test_linha_corrompida_nao_derruba_a_sequencia(self, tmp_path):
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,1.0",
            "1,x,y,200,50,150,1,1,1.0",
            "2,1,110,200,50,150,1,1,1.0",
        ])
        s = gt.carregar_mot(pasta)
        assert len(s.rastros(1)) == 1
        assert len(s.rastros(2)) == 1

    def test_conta_pessoas_distintas(self, tmp_path):
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,1.0",
            "2,1,110,200,50,150,1,1,1.0",
            "2,2,400,200,50,150,1,1,1.0",
        ])
        assert gt.carregar_mot(pasta).pessoas == 2

    def test_padrao_de_imagens_para_o_opencv(self, tmp_path):
        pasta = montar_sequencia(tmp_path, ["1,1,100,200,50,150,1,1,1.0"])
        assert gt.carregar_mot(pasta).padrao_imagens.endswith("img1\\%06d.jpg") or \
               gt.carregar_mot(pasta).padrao_imagens.endswith("img1/%06d.jpg")

    def test_sem_seqinfo_usa_padrao_e_deduz_o_total(self, tmp_path):
        pasta = montar_sequencia(tmp_path, [
            "1,1,100,200,50,150,1,1,1.0",
            "42,1,100,200,50,150,1,1,1.0",
        ], seqinfo=False)
        s = gt.carregar_mot(pasta)
        assert s.fps == 25.0
        assert s.quadros == 42

    def test_sequencia_de_teste_avisa_que_nao_tem_anotacao(self, tmp_path):
        (tmp_path / "MOT17-01").mkdir()
        with pytest.raises(gt.GroundTruthInvalido, match="treino"):
            gt.carregar_mot(tmp_path / "MOT17-01")

    def test_gt_so_com_linhas_descartadas_e_recusado(self, tmp_path):
        pasta = montar_sequencia(tmp_path, ["1,1,100,200,50,150,0,1,1.0"])
        with pytest.raises(gt.GroundTruthInvalido, match="nenhum pedestre"):
            gt.carregar_mot(pasta)


class TestContarNoGroundTruth:
    """A anotação passa pela MESMA linha de contagem do pipeline.

    É isso que isola a variável: o que sai daqui é quantas travessias
    existiriam com detecção e rastreio perfeitos.
    """

    def _linha(self):
        # Vertical em x=500; o lado direito dá -1 e vale como "dentro".
        return LinhaDeContagem(
            camera_id="mot", a=(500.0, 0.0), b=(500.0, 1080.0), lado_dentro=-1,
            idade_minima_track=3, janela_suavizacao=3, zona_morta_px=15.0,
            cooldown_segundos=1.5,
        )

    def test_uma_travessia_da_esquerda_para_a_direita(self, tmp_path):
        # Pé em x = 300..700, y = 900. Caixa: x-25 .. x+25, base em 900.
        linhas = [
            f"{q},1,{x - 25},750,50,150,1,1,1.0"
            for q, x in enumerate([300, 350, 400, 450, 560, 620, 700], start=1)
        ]
        s = gt.carregar_mot(montar_sequencia(tmp_path, linhas))
        eventos = gt.contar_no_ground_truth(s, self._linha(), INICIO)
        assert len(eventos) == 1
        assert eventos[0].direcao is Direcao.ENTRADA

    def test_duas_pessoas_em_sentidos_opostos(self, tmp_path):
        linhas = []
        for q, (a, b) in enumerate(
            [(300, 700), (350, 650), (400, 600), (450, 550), (560, 440), (620, 380)],
            start=1,
        ):
            linhas.append(f"{q},1,{a - 25},750,50,150,1,1,1.0")
            linhas.append(f"{q},2,{b - 25},750,50,150,1,1,1.0")
        s = gt.carregar_mot(montar_sequencia(tmp_path, linhas))
        eventos = gt.contar_no_ground_truth(s, self._linha(), INICIO)
        assert {e.direcao for e in eventos} == {Direcao.ENTRADA, Direcao.SAIDA}
        assert len(eventos) == 2

    def test_quem_nao_alcanca_a_linha_nao_conta(self, tmp_path):
        linhas = [
            f"{q},1,{x - 25},750,50,150,1,1,1.0"
            for q, x in enumerate([300, 320, 340, 360, 380, 400], start=1)
        ]
        s = gt.carregar_mot(montar_sequencia(tmp_path, linhas))
        assert gt.contar_no_ground_truth(s, self._linha(), INICIO) == []
