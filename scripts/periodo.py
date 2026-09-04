"""Períodos de teste nomeados: abrir, encerrar, registrar um passado, listar.

    python scripts/periodo.py --iniciar "Laboratório de física" --camera entrada_real
    python scripts/periodo.py --encerrar                     # fecha o aberto
    python scripts/periodo.py --encerrar "Laboratório de física"
    python scripts/periodo.py --registrar "Teste de campo 03/09" \
        --inicio 2026-09-03T15:19:39 --fim 2026-09-03T18:26:41 --camera entrada_real
    python scripts/periodo.py --renomear "Teste 1" "Teste de campo 03/09"
    python scripts/periodo.py --listar

O período é um rótulo sobre um intervalo: não apaga nem move evento nenhum.
Escreve direto no banco, como criar_banco.py — pode rodar com tudo de pé.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.dominio.evento import FUSO_LOCAL
from fluxo.persistencia import repositorio


def _instante(texto: str | None) -> datetime | None:
    if not texto:
        return None
    valor = datetime.fromisoformat(texto)
    return valor.replace(tzinfo=FUSO_LOCAL) if valor.tzinfo is None else valor


def _listar(conn) -> None:
    periodos = repositorio.listar_periodos(conn)
    if not periodos:
        print("Nenhum período registrado.")
        return
    for p in periodos:
        onde = p.camera_id or "todas"
        print(f"  [{p.id}] {p.rotulo()}  ({onde})")


def main() -> None:
    p = argparse.ArgumentParser(description="Períodos de teste do Limiar")
    acao = p.add_mutually_exclusive_group(required=True)
    acao.add_argument("--iniciar", metavar="NOME", help="Abre um período agora (ou em --em)")
    acao.add_argument("--encerrar", nargs="?", const="", metavar="NOME",
                      help="Fecha o período (sem nome: o aberto mais recente)")
    acao.add_argument("--registrar", metavar="NOME",
                      help="Registra um período já passado; exige --inicio e --fim")
    acao.add_argument("--renomear", nargs=2, metavar=("DE", "PARA"))
    acao.add_argument("--listar", action="store_true")
    p.add_argument("--camera", default=None, help="Id em config/cameras.yaml (padrão: todas)")
    p.add_argument("--em", default=None, help="Início do --iniciar, ISO (padrão: agora)")
    p.add_argument("--inicio", default=None, help="ISO, ex.: 2026-09-03T15:19:39")
    p.add_argument("--fim", default=None, help="ISO; no --encerrar, padrão: agora")
    p.add_argument("--obs", default=None, help="Observação livre")
    args = p.parse_args()

    config.garantir_pastas()
    conn = repositorio.conectar()
    try:
        repositorio.criar_banco(conn)
        if args.listar:
            _listar(conn)
        elif args.iniciar:
            aberto = repositorio.periodo_aberto(conn)
            if aberto is not None:
                print(f"Atenção: '{aberto.nome}' continua aberto. "
                      f"Encerre com --encerrar se este substitui aquele.")
            periodo = repositorio.criar_periodo(
                conn, args.iniciar, _instante(args.em) or datetime.now(FUSO_LOCAL),
                camera_id=args.camera, observacao=args.obs,
            )
            print(f"Aberto: {periodo.rotulo()}")
        elif args.encerrar is not None:
            alvo: int | str
            if args.encerrar:
                alvo = args.encerrar
            else:
                aberto = repositorio.periodo_aberto(conn)
                if aberto is None or aberto.id is None:
                    sys.exit("Nenhum período aberto.")
                alvo = aberto.id
            periodo = repositorio.encerrar_periodo(conn, alvo, _instante(args.fim))
            print(f"Encerrado: {periodo.rotulo()}")
        elif args.registrar:
            if not args.inicio or not args.fim:
                sys.exit("--registrar exige --inicio e --fim.")
            periodo = repositorio.criar_periodo(
                conn, args.registrar, _instante(args.inicio), _instante(args.fim),
                camera_id=args.camera, observacao=args.obs,
            )
            print(f"Registrado: {periodo.rotulo()}")
        elif args.renomear:
            de, para = args.renomear
            periodo = repositorio.renomear_periodo(conn, de, para)
            print(f"Renomeado: {periodo.rotulo()}")
    except repositorio.PeriodoDuplicado as erro:
        sys.exit(f"Já existe um período chamado '{erro}'.")
    except repositorio.PeriodoDesconhecido as erro:
        sys.exit(f"Período não encontrado: {erro}. Veja --listar.")
    except repositorio.CameraDesconhecida as erro:
        sys.exit(f"Câmera '{erro}' não está no banco. Rode scripts/criar_banco.py.")
    except ValueError as erro:
        sys.exit(str(erro))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
