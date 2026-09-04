"""Instala (ou remove) a partida automática do Limiar no logon do Windows.

    python scripts/instalar_logon.py entrada_real --tunel
    python scripts/instalar_logon.py --consultar
    python scripts/instalar_logon.py --executar      # sobe agora, sem relogar
    python scripts/instalar_logon.py --remover

Não precisa de admin: a tarefa é do próprio usuário e roda quando ele entra.
O que ela lança é `rodar_tudo.py` com o python do ambiente do projeto — sem
limite de 72 h, relançando se cair (o XML em fluxo.operacao.agendador).
Depois tenta desligar a suspensão da máquina com `powercfg`; se isso exigir
admin, avisa e segue, porque o supervisor segura a máquina acordada sozinho
enquanto vive. Passo a passo completo em docs/operacao.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from fluxo import config
from fluxo.ambiente import interpretador_do_projeto
from fluxo.operacao import agendador, energia


def _rodar(comando: list[str]) -> int:
    print("> " + " ".join(comando))
    return subprocess.run(comando, check=False).returncode


def _usuario_atual() -> str:
    dominio = os.environ.get("USERDOMAIN", "")
    nome = os.environ.get("USERNAME", "")
    return f"{dominio}\\{nome}" if dominio else nome


def _ajustar_energia() -> None:
    print("\nEnergia: desligando a suspensão automática (pode exigir admin).")
    for comando in energia.comandos_powercfg():
        if _rodar(comando) != 0:
            print("  Não deu — sem admin, provavelmente. O supervisor segura a máquina "
                  "acordada enquanto roda; peça ao TI para desativar a suspensão.")
            return
    print("  Feito: a máquina não dorme ligada na tomada.")


def main() -> None:
    p = argparse.ArgumentParser(description="Partida do Limiar no logon (Windows)")
    p.add_argument("camera", nargs="?", help="Id da câmera ao vivo em config/cameras.yaml")
    p.add_argument("--host-servico", default=None,
                   help="Passe 0.0.0.0 só se outra máquina for falar com o serviço")
    p.add_argument("--tunel", action="store_true",
                   help="O supervisor sobe também o túnel do painel (rodar_tudo.py --tunel)")
    p.add_argument("--nome", default=agendador.NOME_TAREFA,
                   help="Nome da tarefa (para testar sem tocar na de verdade)")
    p.add_argument("--sem-energia", action="store_true", help="Não mexe no powercfg")
    p.add_argument("--remover", action="store_true")
    p.add_argument("--consultar", action="store_true")
    p.add_argument("--executar", action="store_true", help="Dispara a tarefa agora")
    args = p.parse_args()

    if os.name != "nt":
        sys.exit("Este instalador é para Windows. Em Linux, use um serviço de usuário "
                 "do systemd apontando para scripts/rodar_tudo.py.")

    if args.remover:
        sys.exit(_rodar(agendador.comando_remover(args.nome)))
    if args.consultar:
        sys.exit(_rodar(agendador.comando_consultar(args.nome)))
    if args.executar:
        sys.exit(_rodar(agendador.comando_executar(args.nome)))

    if not args.camera:
        sys.exit("Passe a câmera: python scripts/instalar_logon.py entrada_real --tunel")
    python = interpretador_do_projeto(exigir_visao=True)
    if python is None:
        sys.exit("Ambiente do projeto não encontrado. Rode `uv sync --extra visao` antes.")

    script = RAIZ / "scripts" / "rodar_tudo.py"
    config.garantir_pastas()
    arquivo_xml = config.CAMINHO_LOGS / f"tarefa-{args.nome.lower()}.xml"
    arquivo_xml.write_text(
        agendador.xml_da_tarefa(
            python, script, args.camera, _usuario_atual(),
            host_servico=args.host_servico, tunel=args.tunel, pasta_de_trabalho=RAIZ,
        ),
        encoding="utf-16",
    )

    codigo = _rodar(agendador.comando_criar(arquivo_xml, args.nome))
    if codigo != 0:
        print("\nO Agendador recusou o XML. Tentando o comando simples — funciona, mas "
              "herda o limite de 72 h do Windows: reinstale com o XML quando puder.")
        codigo = _rodar(agendador.comando_criar_simples(
            python, script, args.camera, args.nome,
            host_servico=args.host_servico, tunel=args.tunel,
        ))
    if codigo != 0:
        sys.exit(codigo)

    print(f"\nTarefa '{args.nome}' instalada. Sobe no próximo logon; para subir agora:\n"
          f"  python scripts/instalar_logon.py --executar --nome {args.nome}")
    if not args.sem_energia:
        _ajustar_energia()


if __name__ == "__main__":
    main()
