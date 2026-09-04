"""O que a Etapa 2 acrescenta ao dado — e o que ela NÃO acrescenta.

`PessoaSessao` é um pseudônimo do dia ("P7"): existe enquanto a roupa é a
mesma, expira por construção e não aponta para ninguém. `Vinculo` liga um
evento de cruzamento a um pseudônimo, ou a nenhum — o "não atribuído" é dado
de primeira classe, porque é ele que torna o resultado honesto (PROJETO §12).

`Apelido` só existe para o teste de validação com pessoas conhecidas. Em
operação nunca é enviado.

Compartilhado por agente e serviço pelo mesmo motivo que `evento.py`: uma
definição só.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from fluxo.dominio.evento import FUSO_LOCAL

Metodo = Literal["nova", "reentrada", "saida", "nao_atribuido"]


def _com_fuso(v: datetime) -> datetime:
    return v.replace(tzinfo=FUSO_LOCAL) if v.tzinfo is None else v


class PessoaSessao(BaseModel):
    camera_id: str = Field(min_length=1, max_length=64)
    data_ref: date
    pseudonimo: str = Field(min_length=1, max_length=16)
    primeiro_visto: datetime
    ultimo_visto: datetime

    @field_validator("primeiro_visto", "ultimo_visto")
    @classmethod
    def _garantir_fuso(cls, v: datetime) -> datetime:
        return _com_fuso(v)


class Vinculo(BaseModel):
    id_evento: str = Field(min_length=1, max_length=200)
    camera_id: str = Field(min_length=1, max_length=64)
    data_ref: date
    pseudonimo: str | None = Field(default=None, max_length=16)
    similaridade: float | None = Field(default=None, ge=-1.0, le=1.0)
    atribuido: bool
    metodo: Metodo


class Apelido(BaseModel):
    camera_id: str = Field(min_length=1, max_length=64)
    data_ref: date
    pseudonimo: str = Field(min_length=1, max_length=16)
    apelido: str = Field(min_length=1, max_length=64)


class RespostaVinculos(BaseModel):
    recebidos: int
    gravados: int
