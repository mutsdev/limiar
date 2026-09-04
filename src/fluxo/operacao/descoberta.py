"""Acha a câmera na rede quando o endereço dela muda.

O firmware pega IP por DHCP, e todo reinício pode trazer um endereço novo —
tirar do USB e ligar na tomada é um reinício. Sem o Monitor Serial (que exige
o cabo no PC), não haveria como saber para onde ela foi.

A busca é em duas fases porque a placa aceita **um cliente por vez**: primeiro
uma varredura de porta, barata e paralela, que reduz a rede a um punhado de
candidatos; só depois cada candidato é confirmado abrindo o stream de verdade.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

PORTA_STREAM = 81


def ips_locais() -> list[str]:
    """Endereços IPv4 desta máquina, sem loopback nem APIPA."""
    achados: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            achados.add(info[4][0])
    except OSError:
        pass

    # A rota padrão como reserva: em máquina com nome não resolvível o
    # getaddrinfo acima devolve nada. Não envia pacote — UDP só escolhe a rota.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        achados.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()

    return sorted(
        ip for ip in achados
        if not ip.startswith(("127.", "169.254.")) and ip.count(".") == 3
    )


def redes_para_varrer(ips: Iterable[str]) -> list[str]:
    """O /24 de cada endereço local.

    A máscara real costuma ser /16 nas redes de instituição, mas varrer 65 mil
    endereços leva minutos e não paga: o DHCP entrega dentro da mesma faixa /24
    do resto dos clientes em praticamente todo roteador.
    """
    redes: list[str] = []
    for ip in ips:
        try:
            rede = ipaddress.ip_network(f"{ip}/24", strict=False)
        except ValueError:
            continue
        if str(rede) not in redes:
            redes.append(str(rede))
    return redes


def porta_aberta(ip: str, porta: int = PORTA_STREAM, timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((ip, porta)) == 0


def varrer(
    rede: str,
    porta: int = PORTA_STREAM,
    timeout: float = 0.4,
    trabalhadores: int = 128,
    sonda: Callable[[str, int, float], bool] | None = None,
) -> list[str]:
    """IPs da rede com a porta aberta. `sonda` é injetável para teste."""
    sonda = sonda or porta_aberta
    hosts = [str(h) for h in ipaddress.ip_network(rede, strict=False).hosts()]
    with ThreadPoolExecutor(max_workers=trabalhadores) as executor:
        abertos = executor.map(lambda ip: (ip, sonda(ip, porta, timeout)), hosts)
        return [ip for ip, aberto in abertos if aberto]


def url_do_stream(ip: str, porta: int = PORTA_STREAM) -> str:
    return f"http://{ip}:{porta}/stream"


def confirmar(
    ips: Iterable[str],
    porta: int = PORTA_STREAM,
    confere: Callable[[str], bool] | None = None,
) -> list[str]:
    """Dos candidatos, os que realmente servem MJPEG.

    Em série, e não em paralelo: a placa atende um cliente por vez, e abrir
    várias conexões de uma vez faria candidatos legítimos parecerem mudos.
    """
    if confere is None:
        from fluxo.visao.fonte_mjpeg import parece_mjpeg

        confere = parece_mjpeg
    return [ip for ip in ips if confere(url_do_stream(ip, porta))]
