"""Entrega dos eventos ao serviço central.

Reenvio é seguro por construção: cada evento carrega uma chave determinística,
e o serviço reconhece a repetição. Isso é o que permite tentar de novo sem
medo de inflar a contagem.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from fluxo.agente.fila_local import FilaLocal
from fluxo.dominio.evento import EventoCruzamento
from fluxo.dominio.identidade import Apelido, PessoaSessao, Vinculo


@dataclass
class Remetente:
    url: str
    fila: FilaLocal
    timeout: float = 5.0
    tentativas: int = 3
    espera_inicial: float = 0.5
    # Vai no header X-Chave-API quando o serviço exige (config.CHAVE_API).
    # Vazia não manda header nenhum — serviço aberto continua funcionando.
    chave: str = ""
    # Etapa 2. Fila separada da de eventos: as duas guardam modelos diferentes,
    # e misturá-las faria a drenagem de uma corromper a outra.
    fila_vinculos: FilaLocal | None = None

    enviados: int = field(default=0, init=False)
    enfileirados: int = field(default=0, init=False)

    def _cabecalhos(self) -> dict[str, str]:
        return {"X-Chave-API": self.chave} if self.chave else {}

    def _postar_json(self, rota: str, corpo: list) -> bool:
        espera = self.espera_inicial
        for tentativa in range(1, self.tentativas + 1):
            try:
                r = httpx.post(
                    f"{self.url}{rota}", json=corpo, timeout=self.timeout,
                    headers=self._cabecalhos(),
                )
                r.raise_for_status()
                return True
            except (httpx.HTTPError, httpx.TimeoutException):
                if tentativa == self.tentativas:
                    return False
                time.sleep(espera)
                espera *= 2  # recuo exponencial: rede caída não melhora insistindo
        return False

    def _postar(self, eventos: list[EventoCruzamento]) -> bool:
        return self._postar_json("/eventos/lote", [e.model_dump(mode="json") for e in eventos])

    def enviar(self, eventos: list[EventoCruzamento]) -> bool:
        """Tenta enviar. O que não for aceito vai para a fila, não se perde."""
        if not eventos:
            return True
        if self._postar(eventos):
            self.enviados += len(eventos)
            return True
        self.enfileirados += self.fila.enfileirar(eventos)
        return False

    def drenar_fila(self) -> int:
        """Reenvia o que ficou acumulado. Devolve quantos saíram."""
        pendentes = self.fila.ler()
        if not pendentes:
            return 0
        if self._postar(pendentes):
            self.fila.limpar()
            self.enviados += len(pendentes)
            return len(pendentes)
        return 0

    def servico_no_ar(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/saude", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def abrir_execucao(
        self,
        camera_id: str,
        fonte: str,
        modelo: str,
        rastreador: str,
        conf_minima: float,
        versao_codigo: str = "",
    ) -> int | None:
        """Registra o início da execução. None se o serviço não responder.

        Falhar aqui não pode derrubar a contagem: rastreabilidade é
        desejável, contar é obrigatório.
        """
        try:
            r = httpx.post(
                f"{self.url}/execucoes",
                json={
                    "camera_id": camera_id,
                    "fonte": fonte,
                    "modelo": modelo,
                    "rastreador": rastreador,
                    "conf_minima": conf_minima,
                    "versao_codigo": versao_codigo,
                },
                timeout=self.timeout,
                headers=self._cabecalhos(),
            )
            r.raise_for_status()
            return int(r.json()["execucao_id"])
        except (httpx.HTTPError, KeyError, ValueError):
            return None

    def fechar_execucao(self, execucao_id: int, quadros: int, eventos: int) -> bool:
        try:
            r = httpx.post(
                f"{self.url}/execucoes/{execucao_id}/fim",
                json={"quadros": quadros, "eventos": eventos},
                timeout=self.timeout,
                headers=self._cabecalhos(),
            )
            r.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Etapa 2. Nada aqui pode derrubar a contagem: identidade é desejável,
    # contar é obrigatório — o mesmo princípio de abrir_execucao.
    # ------------------------------------------------------------------

    def registrar_pessoas(self, pessoas: list[PessoaSessao]) -> bool:
        """Sem fila: se falhar, o vínculo cria a pessoa do lado do serviço."""
        if not pessoas:
            return True
        return self._postar_json("/pessoas/lote", [p.model_dump(mode="json") for p in pessoas])

    def enviar_vinculos(self, vinculos: list[Vinculo]) -> bool:
        if not vinculos:
            return True
        if self._postar_json("/vinculos/lote", [v.model_dump(mode="json") for v in vinculos]):
            if self.fila_vinculos is not None and self.fila_vinculos.tamanho:
                self.drenar_vinculos()
            return True
        if self.fila_vinculos is not None:
            self.fila_vinculos.enfileirar(vinculos)
        return False

    def drenar_vinculos(self) -> int:
        if self.fila_vinculos is None:
            return 0
        pendentes = self.fila_vinculos.ler()
        if not pendentes:
            return 0
        if self._postar_json("/vinculos/lote", [v.model_dump(mode="json") for v in pendentes]):
            self.fila_vinculos.limpar()
            return len(pendentes)
        return 0

    def aplicar_apelido(self, apelido: Apelido) -> bool:
        try:
            r = httpx.put(
                f"{self.url}/pessoas/apelido",
                json=apelido.model_dump(mode="json"),
                timeout=self.timeout,
                headers=self._cabecalhos(),
            )
            r.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
