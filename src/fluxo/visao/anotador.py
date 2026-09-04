"""Overlay de depuração.

O vídeo anotado não é enfeite: é o instrumento com que se descobre por que a
contagem errou. Erro de detecção, id que troca e linha mal posicionada têm
aparências diferentes na tela, e nenhuma delas aparece num número.
"""

from __future__ import annotations

import cv2

from fluxo.contagem.linha import LinhaDeContagem
from fluxo.dominio.rastro import Rastro

# BGR, que é a ordem do OpenCV.
COR_LINHA = (59, 169, 242)     # âmbar — a linha de contagem
COR_CAIXA = (200, 200, 200)
COR_PE = (180, 195, 67)        # teal — o ponto de referência
COR_TEXTO = (245, 245, 245)
COR_FUNDO = (32, 24, 16)

FONTE = cv2.FONT_HERSHEY_SIMPLEX

# Altura de quadro contra a qual todos os tamanhos abaixo são medidos. Sem isso,
# o mesmo placar que cabe bem num 768x432 vira uma tarja ilegível num 4K — o
# texto tem tamanho fixo, o quadro não.
#
# Vale o dobro da altura em que os tamanhos foram escolhidos a olho: medindo
# contra 432 o painel ficava grande demais em vídeo grande, competindo com a
# cena em vez de anotá-la. O piso de 0,9 protege o vídeo pequeno, que continua
# do tamanho de antes.
ALTURA_BASE = 864


def escala_de(imagem, extra: float = 1.0) -> float:
    """Quanto ampliar o desenho para este quadro.

    Limitada embaixo para não sumir em vídeo pequeno, e em cima para não virar
    outdoor em 4K: o overlay é instrumento de leitura, não o assunto da tela.
    `extra` compensa a redução da janela — encolher a exibição não deveria
    encolher o texto que se está tentando ler.
    """
    return min(3.0, max(0.9, imagem.shape[0] / ALTURA_BASE) * max(0.1, extra))


def desenhar_linha(imagem, linha: LinhaDeContagem, escala: float = 1.0):
    e = escala_de(imagem, escala)
    a = (int(linha.a[0]), int(linha.a[1]))
    b = (int(linha.b[0]), int(linha.b[1]))
    cv2.line(imagem, a, b, COR_LINHA, max(2, int(2 * e)))
    for p in (a, b):
        cv2.circle(imagem, p, max(5, int(5 * e)), COR_LINHA, -1)
    return imagem


def desenhar_rastros(imagem, rastros: list[Rastro], escala: float = 1.0,
                     etiquetas: dict[int, str] | None = None):
    """`etiquetas` troca o id do rastreador pelo pseudônimo da Etapa 2 ("P7")."""
    e = escala_de(imagem, escala)
    fonte = 0.45 * e
    grossura = max(1, int(e))
    for r in rastros:
        x1, y1, x2, y2 = (int(v) for v in r.caixa)
        cv2.rectangle(imagem, (x1, y1), (x2, y2), COR_CAIXA, grossura)

        # O ponto do pé é o que realmente decide o lado da linha. Vê-lo é o
        # que permite entender uma contagem errada.
        px, py = r.ponto_base
        cv2.circle(imagem, (int(px), int(py)), max(4, int(4 * e)), COR_PE, -1)

        nome = etiquetas.get(r.id_local, r.id_local) if etiquetas else r.id_local
        etiqueta = f"{nome} {r.confianca:.2f}"
        (lt, at), _ = cv2.getTextSize(etiqueta, FONTE, fonte, grossura)
        margem = int(6 * e)
        cv2.rectangle(imagem, (x1, y1 - at - margem), (x1 + lt + margem, y1),
                      COR_FUNDO, -1)
        cv2.putText(imagem, etiqueta, (x1 + int(3 * e), y1 - int(4 * e)), FONTE,
                    fonte, COR_TEXTO, grossura)
    return imagem


def desenhar_placar(
    imagem, linha: LinhaDeContagem, quadro: int, visiveis: int = 0, extra: str = "",
    escala: float = 1.0,
):
    # "visiveis" é quem está no quadro agora; "memoria" inclui os tracks ainda
    # não esquecidos. Confundir os dois faz o placar parecer errado quando a
    # cena está vazia.
    linhas = [
        f"{linha.camera_id}",
        f"ENTRADAS  {linha.entradas}",
        f"SAIDAS    {linha.saidas}",
        f"quadro {quadro}  visiveis {visiveis}  memoria {linha.rastros_ativos}",
    ]
    if extra:
        linhas.append(extra)

    e = escala_de(imagem, escala)
    fonte = 0.55 * e
    grossura = max(1, int(1.5 * e))
    passo = int(24 * e)
    borda = int(8 * e)

    largura = max(
        cv2.getTextSize(t, FONTE, fonte, grossura)[0][0] for t in linhas
    ) + int(20 * e)
    altura = passo * len(linhas) + int(12 * e)
    # Um painel maior que o quadro estouraria a fatia e o addWeighted daria erro
    # de forma — acontece em vídeo pequeno com texto grande.
    largura = min(largura, imagem.shape[1] - 2 * borda)
    altura = min(altura, imagem.shape[0] - 2 * borda)

    fatia = imagem[borda : borda + altura, borda : borda + largura]
    painel = fatia.copy()
    cv2.rectangle(painel, (0, 0), (largura, altura), COR_FUNDO, -1)
    cv2.addWeighted(painel, 0.75, fatia, 0.25, 0, fatia)

    for i, texto in enumerate(linhas):
        cor = COR_LINHA if i == 1 else (COR_PE if i == 2 else COR_TEXTO)
        cv2.putText(imagem, texto, (borda + int(10 * e), borda + int(24 * e) + i * passo),
                    FONTE, fonte, cor, grossura, cv2.LINE_AA)
    return imagem


def anotar(imagem, linha: LinhaDeContagem, rastros: list[Rastro], quadro: int,
           extra="", escala: float = 1.0, etiquetas: dict[int, str] | None = None):
    desenhar_linha(imagem, linha, escala)
    desenhar_rastros(imagem, rastros, escala, etiquetas)
    desenhar_placar(imagem, linha, quadro, len(rastros), extra, escala)
    return imagem


class JanelaAoVivo:
    """Mostra a contagem acontecendo, em vez de entregar um arquivo no fim.

    O ritmo é acertado aqui, e não na leitura do vídeo: se o processamento for
    mais rápido que o vídeo, esperamos; se for mais lento, seguimos sem tentar
    recuperar o atraso — numa câmera de verdade o quadro velho não interessa.
    """

    TECLAS_SAIR = (27, ord("q"), ord("Q"))
    TECLAS_PAUSA = (32, ord("p"), ord("P"))

    def __init__(self, titulo: str, fps: float = 25.0, velocidade: float = 1.0,
                 escala: float = 1.0) -> None:
        self.titulo = titulo
        self.intervalo = 1.0 / max(1e-6, fps * max(0.01, velocidade))
        self.escala = escala
        self.pausado = False
        self._proximo = None
        cv2.namedWindow(titulo, cv2.WINDOW_NORMAL)

    def _desenhar_estado(self, imagem):
        if self.pausado:
            e = escala_de(imagem)
            texto = "PAUSADO - espaco continua"
            (largura, altura), _ = cv2.getTextSize(texto, FONTE, 0.7 * e, max(2, int(2 * e)))
            x = (imagem.shape[1] - largura) // 2
            y = imagem.shape[0] - 24
            cv2.rectangle(imagem, (x - 10, y - altura - 10), (x + largura + 10, y + 10),
                          COR_FUNDO, -1)
            cv2.putText(imagem, texto, (x, y), FONTE, 0.7 * e, COR_LINHA,
                        max(2, int(2 * e)), cv2.LINE_AA)
        else:
            e = escala_de(imagem)
            cv2.putText(imagem, "q sai  |  espaco pausa",
                        (int(12 * e), imagem.shape[0] - int(12 * e)), FONTE,
                        0.45 * e, (150, 150, 150), max(1, int(e)), cv2.LINE_AA)
        return imagem

    def mostrar(self, imagem) -> bool:
        """Devolve False quando o usuário pede para parar."""
        import time

        tela = imagem if self.escala == 1.0 else cv2.resize(
            imagem, None, fx=self.escala, fy=self.escala, interpolation=cv2.INTER_LINEAR
        )
        self._desenhar_estado(tela)
        cv2.imshow(self.titulo, tela)

        # Fechar a janela no X também precisa encerrar; sem isto o laço
        # continuaria rodando às cegas até o fim do vídeo.
        if cv2.getWindowProperty(self.titulo, cv2.WND_PROP_VISIBLE) < 1:
            return False

        agora = time.monotonic()
        if self._proximo is None:
            self._proximo = agora
        self._proximo += self.intervalo
        espera = self._proximo - agora
        if espera < 0:                       # atrasado: não tenta recuperar
            self._proximo = agora
            espera = 0.0

        tecla = cv2.waitKey(max(1, int(espera * 1000))) & 0xFF
        if tecla in self.TECLAS_SAIR:
            return False
        if tecla in self.TECLAS_PAUSA:
            self.pausado = True
            while self.pausado:
                cv2.imshow(self.titulo, self._desenhar_estado(tela.copy()))
                if cv2.getWindowProperty(self.titulo, cv2.WND_PROP_VISIBLE) < 1:
                    return False
                t = cv2.waitKey(50) & 0xFF
                if t in self.TECLAS_PAUSA:
                    self.pausado = False
                elif t in self.TECLAS_SAIR:
                    return False
            self._proximo = time.monotonic()
        return True

    def fechar(self) -> None:
        cv2.destroyWindow(self.titulo)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()


class GravadorDeVideo:
    """Grava o vídeo anotado. É o entregável visual da apresentação."""

    def __init__(self, caminho, largura: int, altura: int, fps: float) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho = caminho
        self._w = cv2.VideoWriter(
            str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura)
        )
        if not self._w.isOpened():
            raise OSError(f"Não consegui abrir o gravador em {caminho}")

    def escrever(self, imagem) -> None:
        self._w.write(imagem)

    def fechar(self) -> None:
        self._w.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()
