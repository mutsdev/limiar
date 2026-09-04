"""O replay da identidade dá o mesmo que o ao vivo — e varre limiares sem GPU."""

from datetime import datetime, timedelta

from fluxo.avaliacao import identidade as av
from fluxo.avaliacao import trilhas
from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.evento import FUSO_LOCAL, Direcao
from fluxo.dominio.rastro import Rastro
from fluxo.reid.galeria import Galeria

INICIO = datetime(2026, 9, 4, 9, 0, 0, tzinfo=FUSO_LOCAL)
FPS = 25
A = [1.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0]


def nova_linha(**kw):
    padrao = dict(camera_id="entrada_a", a=(450.0, 30.0), b=(450.0, 240.0), lado_dentro=-1,
                  quadros_ate_esquecer=500)
    padrao.update(kw)
    return LinhaDeContagem(**padrao)


def rastro_em(x, track=1):
    return Rastro(id_local=track, caixa=(x - 20, 35.0, x + 20, 135.0), confianca=0.9)


IDA = [300, 340, 380, 420, 480, 520, 560, 600]


def gravar(caminho, passagens):
    """passagens: lista de (quadro_inicial, track, xs, assinatura)."""
    with trilhas.Gravador(caminho, camera="entrada_a") as g:
        eventos = {}
        for q0, track, xs, assinatura in passagens:
            for i, x in enumerate(xs):
                eventos.setdefault(q0 + i, []).append((track, x, assinatura))
        for q in range(max(eventos) + 1):
            rastros = [rastro_em(x, track) for track, x, _ in eventos.get(q, [])]
            g.gravar(q, INICIO + timedelta(seconds=q / FPS), rastros)
            for track, _, assinatura in eventos.get(q, []):
                g.gravar_assinatura(q, track, assinatura)
    return caminho


class TestRecontar:
    def test_entrada_e_saida_da_mesma_pessoa(self, tmp_path):
        # Track 1 entra (esquerda->direita), track 2 sai depois com a mesma aparência.
        caminho = gravar(tmp_path / "t.jsonl", [
            (0, 1, IDA, A),
            (100, 2, list(reversed(IDA)), A),
        ])
        trilha = trilhas.carregar(caminho)
        eventos, decisoes = av.recontar(trilha, nova_linha(), Galeria(janela_lote_s=0))

        assert [e.direcao for e in eventos] == [Direcao.ENTRADA, Direcao.SAIDA]
        assert [(d.direcao, d.pseudonimo) for d in decisoes] == [
            (Direcao.ENTRADA, "P1"), (Direcao.SAIDA, "P1"),
        ]

    def test_pessoa_diferente_sai_sem_par(self, tmp_path):
        caminho = gravar(tmp_path / "t.jsonl", [
            (0, 1, IDA, A),
            (100, 2, list(reversed(IDA)), B),
        ])
        trilha = trilhas.carregar(caminho)
        _, decisoes = av.recontar(trilha, nova_linha(), Galeria(janela_lote_s=0))
        assert decisoes[1].pseudonimo is None

    def test_track_sem_assinatura_conta_mas_nao_decide(self, tmp_path):
        caminho = tmp_path / "t.jsonl"
        with trilhas.Gravador(caminho, camera="entrada_a") as g:
            for i, x in enumerate(IDA):
                g.gravar(i, INICIO + timedelta(seconds=i / FPS), [rastro_em(x)])
        trilha = trilhas.carregar(caminho)
        eventos, decisoes = av.recontar(trilha, nova_linha(), Galeria())
        assert len(eventos) == 1
        assert decisoes == []

    def test_trilha_vazia(self):
        assert av.recontar(trilhas.Trilha(), nova_linha(), Galeria()) == ([], [])


class TestVarrer:
    def test_uma_linha_por_combinacao(self, tmp_path):
        caminho = gravar(tmp_path / "t.jsonl", [
            (0, 1, IDA, A), (100, 2, list(reversed(IDA)), A),
        ])
        trilha = trilhas.carregar(caminho)
        grade = {"limiar_saida": [0.5, 0.9], "limiar_reentrada": [0.7], "janela_lote_s": [0.0]}
        linhas = av.varrer(trilha, nova_linha, Galeria(), grade=grade)
        assert len(linhas) == 2
        assert {linha["limiar_saida"] for linha in linhas} == {0.5, 0.9}
        assert all(linha["pessoas"] == 1 for linha in linhas)
        assert all(linha["sem_par"] == 0 for linha in linhas)

    def test_com_gabarito_sai_pureza(self, tmp_path):
        caminho = gravar(tmp_path / "t.jsonl", [
            (0, 1, IDA, A), (100, 2, list(reversed(IDA)), A),
        ])
        trilha = trilhas.carregar(caminho)
        _, decisoes = av.recontar(trilha, nova_linha(), Galeria(janela_lote_s=0))
        gabarito = {d.id_evento: "maria" for d in decisoes}
        grade = {"limiar_saida": [0.7], "limiar_reentrada": [0.7], "janela_lote_s": [0.0]}
        linhas = av.varrer(trilha, nova_linha, Galeria(), gabarito=gabarito, grade=grade)
        assert linhas[0]["pureza"] == 1.0
        assert linhas[0]["fragmentacao"] == 1.0


class TestGabarito:
    def test_carrega_so_o_preenchido(self, tmp_path):
        csv = tmp_path / "g.csv"
        csv.write_text(
            "id_evento,instante,direcao,pseudonimo,metodo,arquivo,apelido_real\n"
            "e1,2026-09-04T09:00:00-03:00,ENTRADA,P1,nova,P1/a.jpg,maria\n"
            "e2,2026-09-04T09:05:00-03:00,SAIDA,P1,saida,P1/b.jpg,\n"
            "e3,2026-09-04T09:06:00-03:00,SAIDA,,nao_atribuido,_sem_par/c.jpg,  joao \n",
            encoding="utf-8",
        )
        assert av.carregar_gabarito(csv) == {"e1": "maria", "e3": "joao"}

    def test_indice_vira_registros(self, tmp_path):
        csv = tmp_path / "indice.csv"
        csv.write_text(
            "id_evento,instante,direcao,pseudonimo,metodo,arquivo\n"
            "e1,2026-09-04T09:00:00-03:00,ENTRADA,P1,nova,P1/a.jpg\n"
            "e2,2026-09-04T09:05:00-03:00,SAIDA,,nao_atribuido,_sem_par/b.jpg\n",
            encoding="utf-8",
        )
        regs = av.registros_do_indice(csv)
        assert [r.pseudonimo for r in regs] == ["P1", None]
        assert regs[0].direcao is Direcao.ENTRADA
        assert regs[1].instante.hour == 9
