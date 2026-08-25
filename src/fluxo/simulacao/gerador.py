"""Gerador de eventos sintéticos.

Existe para destravar o desenvolvimento: banco, serviço, consultas e painel são
construídos e demonstrados com estes dados, sem que uma linha de visão
computacional precise existir. Se a parte de vídeo atrasar, o resto não para.

Todo evento daqui sai com origem=SINTETICO, e as consultas de resultado
filtram VISAO por padrão. Dado falso não vaza para número de relatório.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from fluxo.dominio.evento import FUSO_LOCAL, Direcao, EventoCruzamento, Origem

# Peso relativo de chegada por hora. A curva tem três picos — começo da manhã,
# almoço e começo da noite — que é o padrão de uma faculdade com três turnos.
PERFIL_CHEGADA: dict[int, float] = {
    7: 18, 8: 12, 9: 6, 10: 5, 11: 4,
    12: 9, 13: 10, 14: 6, 15: 4, 16: 4,
    17: 6, 18: 16, 19: 12, 20: 4, 21: 2, 22: 1,
}

HORA_FECHAMENTO = 23

# Duas populações: quem vem para uma aula e vai embora, e quem passa o turno.
# Modelar como mistura, e não como uma média, é o que produz a distribuição
# bimodal que a etapa 2 vai tentar medir de verdade.
PERMANENCIA_CURTA = (1.6, 0.5)   # (média, desvio) em horas
PERMANENCIA_LONGA = (4.2, 1.1)
FRACAO_CURTA = 0.55

# Fração de pessoas que sai e volta no mesmo dia (almoço, impressão, banco).
FRACAO_REENTRADA = 0.12


def _sortear_hora(rng: random.Random) -> int:
    horas = list(PERFIL_CHEGADA)
    pesos = [PERFIL_CHEGADA[h] for h in horas]
    return rng.choices(horas, weights=pesos, k=1)[0]


def _instante_em(dia: date, hora: int, rng: random.Random) -> datetime:
    return datetime.combine(
        dia, time(hora, rng.randrange(60), rng.randrange(60)), tzinfo=FUSO_LOCAL
    )


def _sortear_permanencia(rng: random.Random) -> timedelta:
    media, desvio = (
        PERMANENCIA_CURTA if rng.random() < FRACAO_CURTA else PERMANENCIA_LONGA
    )
    horas = max(0.15, rng.gauss(media, desvio))
    return timedelta(hours=horas)


def _fechamento(dia: date, rng: random.Random) -> datetime:
    """Quem não saiu antes sai perto do fechamento, não exatamente nele."""
    base = datetime.combine(dia, time(HORA_FECHAMENTO, 0), tzinfo=FUSO_LOCAL)
    return base + timedelta(minutes=rng.gauss(-12, 9))


def gerar_dia(
    dia: date,
    pessoas: int = 900,
    pesos_camera: dict[str, float] | None = None,
    semente: int | None = None,
) -> list[EventoCruzamento]:
    """Gera um dia inteiro de passagens.

    Cada pessoa produz um par entrada/saída, então o balanço do dia fecha em
    zero por construção — que é a propriedade que as consultas de ocupação
    esperam encontrar.
    """
    rng = random.Random(semente)
    pesos = pesos_camera or {"entrada_a": 0.65, "entrada_b": 0.35}
    cameras = list(pesos)
    valores = [pesos[c] for c in cameras]

    eventos: list[EventoCruzamento] = []
    contador = 0

    def registrar(camera: str, instante: datetime, direcao: Direcao) -> None:
        nonlocal contador
        contador += 1
        eventos.append(
            EventoCruzamento(
                camera_id=camera,
                instante=instante,
                direcao=direcao,
                track_id_local=None,
                confianca=round(rng.uniform(0.72, 0.98), 3),
                id_evento=f"sint-{dia.isoformat()}-{contador:06d}",
                origem=Origem.SINTETICO,
            )
        )

    for _ in range(pessoas):
        camera_entrada = rng.choices(cameras, weights=valores, k=1)[0]
        entrada = _instante_em(dia, _sortear_hora(rng), rng)
        saida = entrada + _sortear_permanencia(rng)

        limite = _fechamento(dia, rng)
        if saida > limite:
            saida = limite

        # A maioria sai pela porta que usou para entrar, mas não todos — é
        # justamente esse resíduo que a etapa 2 vai tentar quantificar.
        camera_saida = (
            camera_entrada
            if rng.random() < 0.72
            else rng.choice([c for c in cameras if c != camera_entrada] or [camera_entrada])
        )

        registrar(camera_entrada, entrada, Direcao.ENTRADA)

        if rng.random() < FRACAO_REENTRADA and saida - entrada > timedelta(hours=1.2):
            # Sai no meio e volta: dois pares em vez de um.
            pausa_inicio = entrada + (saida - entrada) * rng.uniform(0.3, 0.6)
            pausa_fim = pausa_inicio + timedelta(minutes=rng.uniform(25, 80))
            if pausa_fim < saida:
                registrar(camera_saida, pausa_inicio, Direcao.SAIDA)
                registrar(camera_saida, pausa_fim, Direcao.ENTRADA)

        registrar(camera_saida, saida, Direcao.SAIDA)

    eventos.sort(key=lambda e: e.instante)
    return eventos


def gerar_periodo(
    inicio: date,
    dias: int,
    pessoas_base: int = 900,
    semente: int | None = None,
    pular_domingo: bool = True,
) -> list[EventoCruzamento]:
    """Vários dias seguidos, com variação por dia da semana.

    Sexta é mais fraca e sábado bem mais — a variação existe para que as
    consultas por dia da semana tenham o que mostrar.
    """
    rng = random.Random(semente)
    fator_por_dia = {0: 1.05, 1: 1.10, 2: 1.08, 3: 1.02, 4: 0.85, 5: 0.35, 6: 0.0}

    eventos: list[EventoCruzamento] = []
    for i in range(dias):
        dia = inicio + timedelta(days=i)
        fator = fator_por_dia[dia.weekday()]
        if fator == 0.0 and pular_domingo:
            continue
        pessoas = int(pessoas_base * fator * rng.uniform(0.92, 1.08))
        eventos.extend(gerar_dia(dia, pessoas, semente=rng.randrange(1 << 30)))
    return eventos
