"""Chave de API das rotas de escrita.

Sem `CHAVE_API` no ambiente o serviço fica aberto — o certo para localhost,
e o que mantém os testes e o primeiro teste de campo sem fricção. Definida a
chave, as rotas de escrita passam a exigir o header `X-Chave-API`; as de
consulta continuam abertas, porque servem agregados sem identidade.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from fluxo import config


def exigir_chave(x_chave_api: Annotated[str | None, Header()] = None) -> None:
    # Lida a cada requisição, e não na importação: permite ligar/desligar em
    # teste e garante que o valor é o do processo que está servindo.
    esperada = config.CHAVE_API
    if not esperada:
        return
    if x_chave_api is None or not secrets.compare_digest(x_chave_api, esperada):
        raise HTTPException(status_code=401, detail="Chave de API ausente ou incorreta.")
