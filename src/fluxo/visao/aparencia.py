"""Aparência: do recorte da pessoa ao vetor que a representa hoje.

Único módulo do re-ID que toca torch e cv2. Ele produz `list[float]`; tudo
que decide identidade (`reid/`) consome só isso — e por isso continua
testável sem GPU.

O modelo inicial é o ResNet-18 do torchvision com a cabeça de classificação
removida: 512 números por recorte, pesos já instalados com o extra `visao`,
zero dependência nova. É fraco para re-ID de verdade (foi treinado para dizer
"gato", não "mesma pessoa"), mas com vinte pessoas de roupas distintas pode
bastar — e é isso que a medição vai dizer. Se não bastar, o OSNet entra por
esta mesma interface, trocando uma linha no YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from fluxo.dominio.rastro import Caixa
from fluxo.reid.assinatura import Assinatura, normalizar

MODELOS = ("resnet18", "resnet50", "osnet_x0_25")

# Normalização com que os pesos do torchvision foram treinados.
MEDIA_IMAGENET = (0.485, 0.456, 0.406)
DESVIO_IMAGENET = (0.229, 0.224, 0.225)

# Folga em volta da caixa: o rastreador corta rente, e um pouco de contexto
# (sapato, cabelo) ajuda mais do que atrapalha.
MARGEM = 0.05


@dataclass(slots=True)
class ConfigAparencia:
    modelo: str = "resnet18"
    largura: int = 128
    altura: int = 256
    dispositivo: str = "auto"
    recortes_por_track: int = 5
    intervalo_recorte_quadros: int = 3
    # Para onde o torchvision baixa os pesos na primeira execução.
    pasta_modelos: Path | None = None

    @classmethod
    def de_pipeline(cls, pipeline: dict, pasta_modelos: Path | None = None) -> ConfigAparencia:
        r = pipeline.get("reid", {})
        d = pipeline.get("deteccao", {})
        tamanho = r.get("tamanho_recorte", [128, 256])
        return cls(
            modelo=str(r.get("modelo", "resnet18")),
            largura=int(tamanho[0]),
            altura=int(tamanho[1]),
            # Sem `dispositivo` próprio, segue o do detector: as duas redes
            # dividem a mesma GPU, e não faz sentido uma em cada lugar.
            dispositivo=str(r.get("dispositivo", d.get("dispositivo", "auto"))),
            recortes_por_track=int(r.get("recortes_por_track", 5)),
            intervalo_recorte_quadros=int(r.get("intervalo_recorte_quadros", 3)),
            pasta_modelos=pasta_modelos,
        )


def recortar(imagem, caixa: Caixa, largura: int, altura: int, margem: float = MARGEM):
    """Recorta a caixa do quadro e redimensiona. None se a caixa não tem área.

    Redimensiona sem preservar proporção, de propósito: as redes de re-ID são
    treinadas em 2:1 e esperam isso; uma pessoa "esticada" é o que elas viram
    no treino.
    """
    alt_img, larg_img = imagem.shape[:2]
    x1, y1, x2, y2 = caixa
    mx, my = (x2 - x1) * margem, (y2 - y1) * margem
    x1 = max(0, int(x1 - mx))
    y1 = max(0, int(y1 - my))
    x2 = min(larg_img, int(x2 + mx))
    y2 = min(alt_img, int(y2 + my))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return cv2.resize(imagem[y1:y2, x1:x2], (largura, altura), interpolation=cv2.INTER_LINEAR)


class Extrator:
    """Envolve a rede e devolve assinaturas do domínio."""

    def __init__(self, config: ConfigAparencia | None = None) -> None:
        self.config = config or ConfigAparencia()
        if self.config.pasta_modelos is not None:
            # O torchvision lê TORCH_HOME na hora de baixar. Precisa estar no
            # ambiente antes do import.
            os.environ.setdefault("TORCH_HOME", str(self.config.pasta_modelos))

        import torch  # pesa, e só é necessário aqui

        self._torch = torch
        self._dispositivo = self._resolver_dispositivo()
        self._modelo = self._montar(self.config.modelo).to(self._dispositivo).eval()
        self._media = torch.tensor(MEDIA_IMAGENET).view(1, 3, 1, 1).to(self._dispositivo)
        self._desvio = torch.tensor(DESVIO_IMAGENET).view(1, 3, 1, 1).to(self._dispositivo)

    def _resolver_dispositivo(self) -> str:
        d = self.config.dispositivo
        if d == "auto":
            return "cuda" if self._torch.cuda.is_available() else "cpu"
        # O detector chama a GPU de "0"; o torch puro chama de "cuda:0".
        return f"cuda:{d}" if d.isdigit() else d

    def _montar(self, nome: str):
        if nome in ("resnet18", "resnet50"):
            from torchvision import models

            if nome == "resnet18":
                m = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
            else:
                m = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
            # Sem a cabeça: o que interessa é o vetor antes da classificação.
            m.fc = self._torch.nn.Identity()
            return m
        if nome.startswith("osnet"):
            raise NotImplementedError(
                f"{nome!r} entra na fase 2b, se o resnet18 não separar as pessoas "
                f"(ver docs/resultados.md §9). Por enquanto use modelo: resnet18."
            )
        raise ValueError(f"Modelo de aparência desconhecido: {nome!r}. Opções: {MODELOS}")

    @property
    def dispositivo(self) -> str:
        return self._dispositivo

    @property
    def dimensao(self) -> int:
        return 2048 if self.config.modelo == "resnet50" else 512

    def recortar(self, imagem, caixa: Caixa):
        return recortar(imagem, caixa, self.config.largura, self.config.altura)

    def extrair(self, recortes: list) -> list[Assinatura]:
        """Um lote de recortes entra, uma assinatura por recorte sai."""
        if not recortes:
            return []
        torch = self._torch
        # BGR (OpenCV) -> RGB (torchvision), [0, 255] -> [0, 1].
        lote = np.ascontiguousarray(np.stack([r[:, :, ::-1] for r in recortes]))
        t = torch.from_numpy(lote).to(self._dispositivo).permute(0, 3, 1, 2).float() / 255.0
        t = (t - self._media) / self._desvio
        with torch.inference_mode():
            saida = self._modelo(t)
        return [normalizar(v) for v in saida.float().cpu().tolist()]
