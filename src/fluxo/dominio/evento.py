"""O evento de cruzamento — a única unidade de dado do sistema.

Este módulo é compartilhado pelo agente (que produz) e pelo serviço (que
consome). Ter uma definição só é o que impede os dois lados de divergirem
silenciosamente sobre o formato.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# Fuso fixo do projeto. Ver config.UTC_OFFSET_HORAS para o porquê de não usar
# zoneinfo.
FUSO_LOCAL = timezone(timedelta(hours=-3))

# Hora em que o dia operacional começa. Zero = dia civil.
# Existe como constante nomeada porque uma faculdade que funcionasse de
# madrugada precisaria mudar isto, e a regra não deve ficar espalhada.
HORA_INICIO_DIA = 0


class Direcao(StrEnum):
    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"


class Origem(StrEnum):
    """De onde o evento veio.

    Separar isto permite desenvolver o painel com dados falsos sem risco de
    eles vazarem para o relatório: toda consulta de resultado filtra VISAO.
    """

    VISAO = "VISAO"
    SINTETICO = "SINTETICO"
    MANUAL = "MANUAL"


def data_de_referencia(instante: datetime) -> date:
    """O dia operacional a que o instante pertence."""
    local = instante.astimezone(FUSO_LOCAL)
    return (local - timedelta(hours=HORA_INICIO_DIA)).date()


def montar_id_evento(
    camera_id: str, track_id_local: int | None, direcao: Direcao, instante: datetime
) -> str:
    """Chave determinística de deduplicação.

    O mesmo cruzamento, reenviado depois de uma falha de rede, produz a mesma
    chave — e o serviço reconhece a repetição. Sem isso uma reconexão infla a
    contagem, e o erro é silencioso.
    """
    segundo = int(instante.timestamp())
    return f"{camera_id}-{track_id_local}-{direcao.value}-{segundo}"


class EventoCruzamento(BaseModel):
    """Uma pessoa cruzou a linha de contagem de uma câmera."""

    camera_id: str = Field(min_length=1, max_length=64)
    instante: datetime
    direcao: Direcao
    track_id_local: int | None = None
    confianca: float | None = Field(default=None, ge=0.0, le=1.0)
    id_evento: str = Field(min_length=1, max_length=200)
    origem: Origem = Origem.VISAO

    @field_validator("instante")
    @classmethod
    def _garantir_fuso(cls, v: datetime) -> datetime:
        # Instante sem fuso é ambíguo. Assumimos o fuso local em vez de recusar,
        # porque a origem mais comum é um relógio local, e recusar quebraria o
        # agente por um detalhe de serialização.
        return v.replace(tzinfo=FUSO_LOCAL) if v.tzinfo is None else v

    @property
    def data_ref(self) -> date:
        return data_de_referencia(self.instante)

    @classmethod
    def criar(
        cls,
        camera_id: str,
        instante: datetime,
        direcao: Direcao,
        track_id_local: int | None = None,
        confianca: float | None = None,
        origem: Origem = Origem.VISAO,
    ) -> EventoCruzamento:
        """Monta o evento derivando a chave de deduplicação."""
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=FUSO_LOCAL)
        return cls(
            camera_id=camera_id,
            instante=instante,
            direcao=direcao,
            track_id_local=track_id_local,
            confianca=confianca,
            id_evento=montar_id_evento(camera_id, track_id_local, direcao, instante),
            origem=origem,
        )


class RespostaEvento(BaseModel):
    registrado: bool
    id_evento: str
    detalhe: str = ""


class RespostaLote(BaseModel):
    recebidos: int
    registrados: int
    duplicados: int
