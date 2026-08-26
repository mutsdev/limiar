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


def desenhar_linha(imagem, linha: LinhaDeContagem):
    a = (int(linha.a[0]), int(linha.a[1]))
    b = (int(linha.b[0]), int(linha.b[1]))
    cv2.line(imagem, a, b, COR_LINHA, 2)
    for p in (a, b):
        cv2.circle(imagem, p, 5, COR_LINHA, -1)
    return imagem


def desenhar_rastros(imagem, rastros: list[Rastro]):
    for r in rastros:
        x1, y1, x2, y2 = (int(v) for v in r.caixa)
        cv2.rectangle(imagem, (x1, y1), (x2, y2), COR_CAIXA, 1)

        # O ponto do pé é o que realmente decide o lado da linha. Vê-lo é o
        # que permite entender uma contagem errada.
        px, py = r.ponto_base
        cv2.circle(imagem, (int(px), int(py)), 4, COR_PE, -1)

        etiqueta = f"{r.id_local} {r.confianca:.2f}"
        (lt, at), _ = cv2.getTextSize(etiqueta, FONTE, 0.45, 1)
        cv2.rectangle(imagem, (x1, y1 - at - 6), (x1 + lt + 6, y1), COR_FUNDO, -1)
        cv2.putText(imagem, etiqueta, (x1 + 3, y1 - 4), FONTE, 0.45, COR_TEXTO, 1)
    return imagem


def desenhar_placar(
    imagem, linha: LinhaDeContagem, quadro: int, visiveis: int = 0, extra: str = ""
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

    largura = max(cv2.getTextSize(t, FONTE, 0.55, 1)[0][0] for t in linhas) + 20
    altura = 24 * len(linhas) + 12

    painel = imagem[8 : 8 + altura, 8 : 8 + largura].copy()
    cv2.rectangle(painel, (0, 0), (largura, altura), COR_FUNDO, -1)
    cv2.addWeighted(painel, 0.75, imagem[8 : 8 + altura, 8 : 8 + largura], 0.25, 0,
                    imagem[8 : 8 + altura, 8 : 8 + largura])

    for i, texto in enumerate(linhas):
        cor = COR_LINHA if i == 1 else (COR_PE if i == 2 else COR_TEXTO)
        cv2.putText(imagem, texto, (18, 32 + i * 24), FONTE, 0.55, cor, 1, cv2.LINE_AA)
    return imagem


def anotar(imagem, linha: LinhaDeContagem, rastros: list[Rastro], quadro: int, extra=""):
    desenhar_linha(imagem, linha)
    desenhar_rastros(imagem, rastros)
    desenhar_placar(imagem, linha, quadro, len(rastros), extra)
    return imagem


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
