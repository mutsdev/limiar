"""Período de teste: um nome sobre um intervalo de tempo.

"Teste de campo 03/09" e "Laboratório de física" são rótulos que o João Pedro
dá a um trecho da série, para ver só aquele trecho no painel e no relatório.
O período não muda o evento — é lido por cima dele na consulta — e por isso
pode ser criado depois, renomeado, ou encerrado sem tocar em nenhuma contagem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from fluxo.dominio.evento import FUSO_LOCAL, data_de_referencia


@dataclass(frozen=True, slots=True)
class Periodo:
    id: int | None
    nome: str
    inicio: datetime
    fim: datetime | None = None
    camera_id: str | None = None
    observacao: str | None = None

    @property
    def aberto(self) -> bool:
        return self.fim is None

    def datas(self, agora: datetime | None = None) -> tuple[date, date]:
        """Os dias operacionais que o período toca — o filtro grosso, para o SQL.

        O recorte fino, por instante, é feito depois em pandas
        (`consultas.recortar`), porque o banco só indexa `data_ref`.
        """
        fim = self.fim if self.fim is not None else (agora or datetime.now(FUSO_LOCAL))
        return data_de_referencia(self.inicio), data_de_referencia(fim)

    def contem(self, instante: datetime) -> bool:
        if instante < self.inicio:
            return False
        return self.fim is None or instante <= self.fim

    def rotulo(self) -> str:
        """Como o período aparece numa legenda: nome, de quando a quando."""
        inicio = self.inicio.astimezone(FUSO_LOCAL)
        if self.fim is None:
            return f"{self.nome} — desde {inicio:%d/%m %H:%M} (em andamento)"
        fim = self.fim.astimezone(FUSO_LOCAL)
        mesmo_dia = inicio.date() == fim.date()
        ate = f"{fim:%H:%M}" if mesmo_dia else f"{fim:%d/%m %H:%M}"
        return f"{self.nome} — {inicio:%d/%m %H:%M} até {ate}"
