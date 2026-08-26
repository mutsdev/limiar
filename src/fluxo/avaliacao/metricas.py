"""Erro do contador contra a contagem manual de referência."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErroDirecional:
    direcao: str
    automatico: int
    manual: int

    @property
    def erro_absoluto(self) -> int:
        return abs(self.automatico - self.manual)

    @property
    def erro_percentual(self) -> float:
        if self.manual == 0:
            return 0.0 if self.automatico == 0 else float("inf")
        return self.erro_absoluto / self.manual * 100.0

    @property
    def vies(self) -> int:
        """Positivo = contou demais. Negativo = perdeu passagem."""
        return self.automatico - self.manual


@dataclass(frozen=True, slots=True)
class Avaliacao:
    entrada: ErroDirecional
    saida: ErroDirecional
    mae_janela: float | None = None
    janela_segundos: int = 60

    @property
    def aprovado(self) -> bool:
        """A meta declarada: erro <= 10% em CADA direção.

        Cada direção separadamente, e não na média: uma direção costuma ser
        mais ocluída que a outra, e a média esconderia isso.
        """
        return self.entrada.erro_percentual <= 10.0 and self.saida.erro_percentual <= 10.0

    def relatorio(self) -> str:
        linhas = [
            f"{'direcao':<10} {'auto':>6} {'manual':>7} {'erro':>6} {'erro %':>8} {'vies':>6}",
            "-" * 48,
        ]
        for e in (self.entrada, self.saida):
            linhas.append(
                f"{e.direcao:<10} {e.automatico:>6} {e.manual:>7} "
                f"{e.erro_absoluto:>6} {e.erro_percentual:>7.1f}% {e.vies:>+6}"
            )
        if self.mae_janela is not None:
            linhas.append("")
            linhas.append(f"MAE por janela de {self.janela_segundos}s: {self.mae_janela:.2f}")
        linhas.append("")
        linhas.append("APROVADO" if self.aprovado else "REPROVADO (meta: erro <= 10%)")
        return "\n".join(linhas)


def avaliar(
    entradas_auto: int,
    saidas_auto: int,
    entradas_manual: int,
    saidas_manual: int,
    mae_janela: float | None = None,
    janela_segundos: int = 60,
) -> Avaliacao:
    return Avaliacao(
        entrada=ErroDirecional("ENTRADA", entradas_auto, entradas_manual),
        saida=ErroDirecional("SAIDA", saidas_auto, saidas_manual),
        mae_janela=mae_janela,
        janela_segundos=janela_segundos,
    )


def mae_por_janela(auto: dict[int, int], manual: dict[int, int]) -> float:
    """Erro médio absoluto janela a janela.

    Existe porque totais batem por compensação: uma contagem a mais numa
    janela e uma a menos noutra dão um total perfeito e escondem dois erros.
    """
    janelas = set(auto) | set(manual)
    if not janelas:
        return 0.0
    return sum(abs(auto.get(j, 0) - manual.get(j, 0)) for j in janelas) / len(janelas)
