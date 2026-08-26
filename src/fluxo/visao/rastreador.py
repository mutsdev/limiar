"""Detecção e rastreamento de pessoas.

O `ultralytics` faz os dois numa chamada só (`model.track`), o que é bom: a
cola manual entre detector e rastreador é justamente onde erram as
implementações caseiras.

Por que ByteTrack e não SORT ou DeepSORT: o ByteTrack associa em duas passadas
— primeiro com as detecções de alta confiança, depois tentando casar os tracks
órfãos com as de BAIXA confiança, que os outros descartam. Detecção fraca
geralmente não é ruído, é uma pessoa parcialmente ocluída; se há um track
esperando naquela posição, a evidência fraca basta. Menos track quebrado
significa menos contagem duplicada, que é o modo de falha mais caro daqui.
"""

from __future__ import annotations

from dataclasses import dataclass

from fluxo.dominio.rastro import Rastro

CLASSE_PESSOA = 0  # índice de "person" no COCO


@dataclass(slots=True)
class ConfigVisao:
    modelo: str = "yolo11n.pt"
    confianca_minima: float = 0.30
    iou: float = 0.50
    dispositivo: str = "auto"
    tracker: str = "bytetrack.yaml"

    @classmethod
    def de_pipeline(cls, pipeline: dict) -> ConfigVisao:
        d = pipeline.get("deteccao", {})
        r = pipeline.get("rastreio", {})
        return cls(
            modelo=d.get("modelo", "yolo11n.pt"),
            confianca_minima=float(d.get("confianca_minima", 0.30)),
            iou=float(d.get("iou", 0.50)),
            dispositivo=str(d.get("dispositivo", "auto")),
            tracker=r.get("tracker", "bytetrack.yaml"),
        )


class RastreadorPessoas:
    """Envolve o YOLO + ByteTrack e devolve `Rastro` do domínio.

    Isolar aqui a API do ultralytics evita que o formato de saída dele vaze
    para a camada de contagem — que precisa continuar testável sem GPU.
    """

    def __init__(self, config: ConfigVisao | None = None) -> None:
        from ultralytics import YOLO  # importado aqui: pesa, e nem sempre é usado

        self.config = config or ConfigVisao()
        self.modelo = YOLO(self.config.modelo)
        self._dispositivo = self._resolver_dispositivo()

    def _resolver_dispositivo(self) -> str:
        if self.config.dispositivo != "auto":
            return self.config.dispositivo
        import torch

        return "0" if torch.cuda.is_available() else "cpu"

    @property
    def dispositivo(self) -> str:
        return self._dispositivo

    def atualizar(self, imagem) -> list[Rastro]:
        """Um quadro entra, os rastros daquele quadro saem."""
        resultados = self.modelo.track(
            source=imagem,
            persist=True,  # sem isto o id reinicia a cada quadro e nada funciona
            tracker=self.config.tracker,
            classes=[CLASSE_PESSOA],
            conf=self.config.confianca_minima,
            iou=self.config.iou,
            device=self._dispositivo,
            verbose=False,
        )
        if not resultados:
            return []

        caixas = resultados[0].boxes
        if caixas is None or caixas.id is None:
            # Há detecção mas ainda não há identidade atribuída. Sem id não há
            # trajetória, e sem trajetória não há cruzamento.
            return []

        ids = caixas.id.int().cpu().tolist()
        coords = caixas.xyxy.cpu().tolist()
        confs = caixas.conf.cpu().tolist()

        return [
            Rastro(
                id_local=int(i),
                caixa=(float(c[0]), float(c[1]), float(c[2]), float(c[3])),
                confianca=float(cf),
            )
            for i, c, cf in zip(ids, coords, confs, strict=True)
        ]

    def reiniciar(self) -> None:
        """Zera o estado do rastreador — usado ao trocar de vídeo."""
        if hasattr(self.modelo, "predictor") and self.modelo.predictor is not None:
            trackers = getattr(self.modelo.predictor, "trackers", None)
            if trackers:
                for t in trackers:
                    t.reset()
