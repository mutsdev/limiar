"""Define a linha de contagem de uma câmera.

Dois modos:

    # automático: o rastreador olha por onde as pessoas passam e propõe a linha
    python scripts/calibrar_linha.py --camera minha_porta --fonte video.mp4 --sugerir

    # manual: você clica os pontos no quadro
    python scripts/calibrar_linha.py --camera minha_porta --fonte video.mp4

No modo manual: dois cliques definem a linha, o terceiro marca o lado DE DENTRO
do prédio. Tecla `r` recomeça, `Enter` grava, `Esc` cancela.

A câmera é criada em config/cameras.yaml se ainda não existir — para testar um
vídeo qualquer não é preciso editar YAML à mão.

Isto é um passo próprio, e não um número no código, porque sem ferramenta
ninguém recalibra — e recalibrar é a primeira coisa a fazer quando a contagem
erra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo.ambiente import garantir_venv, id_de_camera

# Reexecuta no ambiente do projeto se este `python` nao for o certo. Precisa
# vir antes de qualquer import que dependa das bibliotecas pesadas.
garantir_venv()

import cv2

from fluxo import config
from fluxo.contagem import geometria

JANELA = "Calibrar linha  |  2 cliques = linha, 3o clique = lado DE DENTRO"

# Deslocamento mínimo em pixels para a trajetória valer como "atravessou".
# Abaixo disso é gente parada, e gente parada não define onde fica a porta.
DESLOCAMENTO_MINIMO = 30

# Quanto perto de uma ponta de trajetoria a linha ainda e considerada
# suspeita de oclusor, e quanto isso pesa contra ela.
RAIO_OCLUSOR = 60
PESO_OCLUSOR = 0.5


def abrir_quadro(fonte: str, indice: int):
    cap = cv2.VideoCapture(str(fonte))
    if not cap.isOpened():
        sys.exit(f"Não consegui abrir: {fonte}")
    if indice:
        cap.set(cv2.CAP_PROP_POS_FRAMES, indice)
    ok, quadro = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"Não consegui ler o quadro {indice} de {fonte}")
    return quadro


def gravar(cameras: dict, camera_id: str, fonte: str, linha, lado_dentro: int,
           nota: str = "") -> None:
    entrada = cameras.setdefault(camera_id, {})
    entrada.setdefault("nome", camera_id)
    entrada.setdefault("local", "")
    entrada.setdefault("ativa", True)
    # `nota` é campo de dado, e não comentário, porque este arquivo é
    # regravado por programa — e yaml.safe_dump não preserva comentário.
    # A lição de calibração precisa sobreviver à próxima recalibração.
    if nota:
        entrada["nota"] = nota
    else:
        entrada.setdefault("nota", "")
    entrada["fonte"] = str(fonte)
    entrada["linha"] = [int(v) for v in linha]
    entrada["lado_dentro"] = int(lado_dentro)
    config.salvar_cameras(cameras)

    print(f"\nGravado em {config.ARQUIVO_CAMERAS}")
    print(f"  {camera_id}: linha={entrada['linha']} lado_dentro={lado_dentro}")
    print(f"\nRode agora:\n  python scripts/processar_video.py {camera_id} "
          f"--sem-envio --anotar")


def prever(quadro, linha, destino: Path) -> None:
    """Desenha a linha sobre o quadro e grava, para conferência.

    A regra do docs/calibracao.md é olhar antes de aceitar: oclusor não aparece
    na trajetória, e linha atrás de pilar perde travessia.
    """
    tela = quadro.copy()
    cv2.line(tela, (int(linha[0]), int(linha[1])), (int(linha[2]), int(linha[3])),
             (59, 169, 242), 3)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destino), tela)
    print(f"Prévia da linha: {destino}")
    print("  Confira: há pilar, poste ou muro em cima dela? Se houver, mova.")


# --------------------------------------------------------------------------
# Modo automático
# --------------------------------------------------------------------------


def sugerir(fonte: str, quadro_base) -> tuple[list[int], int]:
    """Roda o rastreador no vídeo e propõe a vertical mais cruzada.

    O mesmo raciocínio da sugestão a partir do MOTChallenge, só que sem
    anotação: aqui as trajetórias vêm do próprio detector. Menos confiável, e
    por isso a prévia em imagem não é opcional.
    """
    from fluxo.visao.fonte import FonteDeVideo
    from fluxo.visao.rastreador import ConfigVisao, RastreadorPessoas

    pipeline = config.carregar_pipeline()
    video = FonteDeVideo(fonte)
    rastreador = RastreadorPessoas(ConfigVisao.de_pipeline(pipeline))

    print(f"Analisando {video} ...")
    faixas: dict[int, list[float]] = {}
    faixas_y: dict[int, list[float]] = {}
    vistos: dict[int, int] = {}
    # Onde cada trajetória começou e terminou. Track que nasce ou morre sempre
    # no mesmo lugar denuncia um oclusor ali — é o sinal que permite evitar
    # pilar, poste e mesa sem enxergá-los.
    pontas: list[float] = []
    primeiro: dict[int, float] = {}
    ultimo: dict[int, float] = {}
    for q in video:
        for r in rastreador.atualizar(q.imagem):
            x, y = r.ponto_base
            faixa = faixas.setdefault(r.id_local, [x, x])
            faixa[0], faixa[1] = min(faixa[0], x), max(faixa[1], x)
            faixa_y = faixas_y.setdefault(r.id_local, [y, y])
            faixa_y[0], faixa_y[1] = min(faixa_y[0], y), max(faixa_y[1], y)
            vistos[r.id_local] = vistos.get(r.id_local, 0) + 1
            primeiro.setdefault(r.id_local, (x, y))
            ultimo[r.id_local] = (x, y)
    video.fechar()
    pontas = list(primeiro.values()) + list(ultimo.values())

    longos = {i for i, n in vistos.items() if n >= 5}
    uteis_x = {
        i: f for i, f in faixas.items()
        if i in longos and f[1] - f[0] > DESLOCAMENTO_MINIMO
    }
    uteis_y = {
        i: f for i, f in faixas_y.items()
        if i in longos and f[1] - f[0] > DESLOCAMENTO_MINIMO
    }
    if not uteis_x and not uteis_y:
        sys.exit(
            "Ninguém atravessa o quadro neste vídeo — não dá para propor uma linha.\n"
            "Use o modo manual (sem --sugerir) e clique onde a passagem acontece."
        )

    altura, largura = quadro_base.shape[:2]

    def avaliar(faixas_uteis, pontas_1d, limite, margem_frac=0.12):
        """Melhor corte perpendicular a um eixo, penalizando oclusor.

        Ponta de trajetória no meio do quadro é sintoma de oclusão: ali o
        track quebrou. Perto da borda é normal — a pessoa entrou ou saiu de
        cena.
        """
        margem = limite * margem_frac
        suspeitas = [p for p in pontas_1d if margem < p < limite - margem]
        melhor, melhor_nota, melhor_n = 0, -1e9, 0
        for c in range(20, limite - 20, 5):
            n = sum(1 for menor, maior in faixas_uteis.values() if menor < c < maior)
            perto = sum(1 for p in suspeitas if abs(p - c) < RAIO_OCLUSOR)
            nota = n - PESO_OCLUSOR * perto
            if nota > melhor_nota:
                melhor, melhor_nota, melhor_n = c, nota, n
        return melhor, melhor_n, len(suspeitas)

    x_corte, n_x, susp_x = avaliar(uteis_x, [p[0] for p in pontas], largura)
    y_corte, n_y, susp_y = avaliar(uteis_y, [p[1] for p in pontas], altura)

    print(f"  {len(faixas)} pessoas rastreadas, {len(longos)} vistas por tempo bastante")
    print(f"  Linha vertical  em x={x_corte}: cruzada por {n_x}")
    print(f"  Linha horizontal em y={y_corte}: cruzada por {n_y}")

    # A orientação certa é a que mais gente atravessa. Numa câmera zenital,
    # com as pessoas subindo o quadro, a linha tem que ser horizontal — e
    # testar só verticais daria a resposta errada com cara de resposta.
    if n_y > n_x:
        if susp_y:
            print(f"  ({susp_y} pontas de trajetória no meio do quadro, evitadas)")
        print(f"  Escolhida: HORIZONTAL em y = {y_corte}, cruzada por {n_y}")
        # Linha da esquerda para a direita: o lado de cima do quadro dá -1.
        # Quem anda para longe da câmera (sobe) é contado como ENTRADA.
        return [0, y_corte, largura, y_corte], -1

    if susp_x:
        print(f"  ({susp_x} pontas de trajetória no meio do quadro, evitadas)")
    print(f"  Escolhida: VERTICAL em x = {x_corte}, cruzada por {n_x}")
    # Linha de cima para baixo: o lado direito do quadro dá -1.
    return [x_corte, 0, x_corte, altura], -1


# --------------------------------------------------------------------------
# Modo manual
# --------------------------------------------------------------------------


def clicar(quadro_base) -> tuple[list[int], int]:
    cliques: list[tuple[int, int]] = []

    def ao_clicar(evento, x, y, _flags, _param):
        if evento == cv2.EVENT_LBUTTONDOWN and len(cliques) < 3:
            cliques.append((x, y))

    cv2.namedWindow(JANELA, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(JANELA, ao_clicar)

    while True:
        tela = quadro_base.copy()
        for i, c in enumerate(cliques):
            cv2.circle(tela, c, 6, (59, 169, 242) if i < 2 else (180, 195, 67), -1)
        if len(cliques) >= 2:
            cv2.line(tela, cliques[0], cliques[1], (59, 169, 242), 2)
        if len(cliques) == 3:
            cv2.putText(tela, "DENTRO", (cliques[2][0] + 10, cliques[2][1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 195, 67), 2)

        dica = {0: "Clique o inicio da linha", 1: "Clique o fim da linha",
                2: "Clique um ponto DE DENTRO do predio"}.get(
            len(cliques), "Enter grava  |  r recomeca  |  Esc cancela")
        cv2.putText(tela, dica, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (245, 245, 245), 2, cv2.LINE_AA)

        cv2.imshow(JANELA, tela)
        tecla = cv2.waitKey(20) & 0xFF
        if tecla == 27:
            cv2.destroyAllWindows()
            sys.exit("Cancelado.")
        if tecla in (ord("r"), ord("R")):
            cliques.clear()
        if tecla in (13, 10) and len(cliques) == 3:
            break

    cv2.destroyAllWindows()
    (x1, y1), (x2, y2), dentro = cliques
    lado = geometria.lado((x1, y1), (x2, y2), dentro)
    if lado == 0:
        sys.exit("O ponto 'dentro' caiu sobre a própria linha. Rode de novo.")
    return [x1, y1, x2, y2], lado


def main() -> None:
    p = argparse.ArgumentParser(description="Calibração da linha de contagem")
    p.add_argument("video", nargs="?", default=None,
                   help="Arquivo de vídeo, índice de webcam ou URL.")
    p.add_argument("--camera", default=None,
                   help="Id da câmera. Padrão: o nome do arquivo de vídeo.")
    p.add_argument("--fonte", default=None, help="Igual a passar o vídeo solto.")
    p.add_argument("--quadro", type=int, default=0, help="Qual quadro usar de base")
    p.add_argument("--sugerir", action="store_true",
                   help="Propõe a linha a partir das trajetórias, sem cliques")
    p.add_argument("--nota", default="",
                   help="Por que a linha ficou aqui. Sobrevive à recalibração.")
    p.add_argument("--inverter", action="store_true",
                   help="Troca qual lado é 'dentro'. Use se entradas e saídas "
                        "saírem trocadas.")
    args = p.parse_args()

    config.garantir_pastas()
    cameras = config.carregar_cameras()

    # O vídeo pode vir solto ou por --fonte; o id da câmera sai do nome do
    # arquivo quando não for informado, para não obrigar a inventar um nome
    # antes de ver o resultado.
    video = args.video or args.fonte
    camera_id = args.camera or (id_de_camera(video) if video else None)
    if not camera_id:
        sys.exit(
            "Passe o vídeo:\n"
            '  python scripts/calibrar_linha.py "C:/Users/voce/Videos/porta.mp4"'
        )

    fonte = video or (cameras.get(camera_id) or {}).get("fonte")
    if not fonte:
        sys.exit(
            f"Câmera '{camera_id}' não tem fonte gravada. Passe o vídeo:\n"
            f'  python scripts/calibrar_linha.py "C:/Users/voce/Videos/porta.mp4"'
        )
    if camera_id not in cameras:
        print(f"Câmera '{camera_id}' não existia — será criada.")
    args.camera = camera_id

    quadro_base = abrir_quadro(fonte, args.quadro)
    linha, lado_dentro = sugerir(fonte, quadro_base) if args.sugerir else clicar(quadro_base)
    if args.inverter:
        lado_dentro = -lado_dentro
        print(f"  lado 'dentro' invertido para {lado_dentro}")

    gravar(cameras, args.camera, fonte, linha, lado_dentro, args.nota)
    prever(quadro_base, linha, config.CAMINHO_SAIDAS / f"{args.camera}_linha.png")


if __name__ == "__main__":
    main()
