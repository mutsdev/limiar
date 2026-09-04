"""O gabarito: quem era, de verdade, em cada travessia.

    # 1. gera o CSV a partir do índice de miniaturas do dia
    python scripts/rotular_pessoas.py --gerar --camera entrada_real            # último dia
    python scripts/rotular_pessoas.py --gerar --camera entrada_real --data 2026-09-04

    # 2. abra dados/recortes/<data>/<camera>/, olhe as miniaturas e preencha a
    #    coluna apelido_real do CSV (qualquer editor; deixe em branco o que não souber)

    # 3. mede a execução ao vivo contra o gabarito
    python scripts/rotular_pessoas.py --metricas dados/gabaritos/2026-09-04_entrada_real.csv

    # 4. (opcional) grava o apelido majoritário de cada P no serviço
    python scripts/rotular_pessoas.py --aplicar dados/gabaritos/2026-09-04_entrada_real.csv

As miniaturas são imagem de pessoa real e existem só para este passo. Quando o
gabarito estiver preenchido, apague a pasta de recortes.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fluxo import config
from fluxo.agente.identidade import ARQUIVO_INDICE
from fluxo.avaliacao import identidade as av
from fluxo.reid import metricas


def pasta_do_dia(camera: str, data: str | None) -> Path:
    raiz = config.CAMINHO_RECORTES
    if data:
        return raiz / data / camera
    dias = sorted(p for p in raiz.iterdir() if (p / camera).is_dir()) if raiz.exists() else []
    if not dias:
        sys.exit(
            f"Nenhuma pasta de recortes para {camera} em {raiz}.\n"
            f"Rode antes: python scripts/identificar_pessoas.py {camera} --guardar-recortes"
        )
    return dias[-1] / camera


def gerar(camera: str, data: str | None, sobrescrever: bool) -> None:
    pasta = pasta_do_dia(camera, data)
    indice = pasta / ARQUIVO_INDICE
    if not indice.exists():
        sys.exit(f"Não achei {indice}. A pasta existe, mas nenhuma travessia foi gravada?")
    destino = config.CAMINHO_GABARITOS / f"{pasta.parent.name}_{camera}.csv"
    if destino.exists() and not sobrescrever:
        sys.exit(f"{destino} já existe. Use --sobrescrever para refazer (perde o preenchido).")

    linhas = []
    with indice.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            linha["apelido_real"] = ""
            linhas.append(linha)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=av.COLUNAS_GABARITO)
        escritor.writeheader()
        escritor.writerows(linhas)

    por_p = Counter(linha["pseudonimo"] or "(sem par)" for linha in linhas)
    print(f"Gabarito : {destino}")
    print(f"           {len(linhas)} travessias, {len(por_p)} pseudônimos")
    print(f"Miniaturas: {pasta}")
    print()
    print("Preencha a coluna apelido_real olhando as miniaturas. O mesmo apelido para a")
    print("mesma pessoa, sempre — é isso que mede confusão e fragmentação. Depois:")
    print(f"  python scripts/rotular_pessoas.py --metricas \"{destino}\"")


def _indice_do_gabarito(caminho: Path) -> Path:
    # <data>_<camera>.csv -> dados/recortes/<data>/<camera>/indice.csv
    nome = caminho.stem
    data, _, camera = nome.partition("_")
    return config.CAMINHO_RECORTES / data / camera / ARQUIVO_INDICE


def medir(caminho: Path) -> None:
    gabarito = av.carregar_gabarito(caminho)
    indice = _indice_do_gabarito(caminho)
    if not indice.exists():
        sys.exit(f"Não achei o índice {indice} de onde este gabarito saiu.")
    registros = av.registros_do_indice(indice)

    r = metricas.resumo(registros, gabarito)
    print(f"Gabarito  : {caminho}  ({len(gabarito)} de {len(registros)} travessias rotuladas)")
    print()
    print(f"Pessoas   : {r['pessoas']} pseudônimos  |  {r.get('pessoas_reais', 0)} reais")
    print(f"Saídas    : {r['saidas']}  |  sem par {r['sem_par']} ({r['taxa_sem_par']:.0%})")
    print(f"Pureza    : {r.get('pureza', 0):.0%}  ({r.get('confusoes', 0)} confusões)")
    print(f"Fragment. : {r.get('fragmentacao', 0):.2f} P por pessoa  "
          f"({r.get('divididas', 0)} divididas)")
    if r["permanencias"]:
        print(f"Permanência: {r['permanencias']} pares, média {r['permanencia_media_min']:.0f} min")

    pu = metricas.pureza(registros, gabarito)
    fr = metricas.fragmentacao(registros, gabarito)
    print()
    print("Por pseudônimo:")
    for pseudonimo, (apelido, n, certos) in pu.por_pseudonimo.items():
        marca = "" if certos == n else f"   <- {n - certos} de outra pessoa"
        print(f"  {pseudonimo:<5} {apelido:<14} {certos}/{n}{marca}")
    divididas = {a: ps for a, ps in fr.por_apelido.items() if len(ps) > 1}
    if divididas:
        print()
        print("Pessoas divididas em mais de um P:")
        for apelido, ps in sorted(divididas.items()):
            print(f"  {apelido:<14} {', '.join(sorted(ps, key=lambda s: int(s[1:])))}")


def aplicar(caminho: Path) -> None:
    from fluxo.agente.fila_local import FilaLocal
    from fluxo.agente.remetente import Remetente
    from fluxo.dominio.identidade import Apelido

    data_txt, _, camera = caminho.stem.partition("_")
    data_ref = date.fromisoformat(data_txt)
    votos: dict[str, Counter] = defaultdict(Counter)
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            apelido = (linha.get("apelido_real") or "").strip()
            if linha["pseudonimo"] and apelido:
                votos[linha["pseudonimo"]][apelido] += 1
    if not votos:
        sys.exit("Nenhum apelido preenchido no gabarito.")

    remetente = Remetente(
        config.URL_SERVICO, FilaLocal(config.CAMINHO_DADOS / "fila" / "apelidos.jsonl"),
        chave=config.CHAVE_API,
    )
    if not remetente.servico_no_ar():
        sys.exit(f"Serviço fora do ar em {config.URL_SERVICO}. "
                 f"Suba-o: python scripts/rodar_servico.py")

    ok = falhas = 0
    for pseudonimo, contagem in sorted(votos.items(), key=lambda kv: int(kv[0][1:])):
        apelido, n = contagem.most_common(1)[0]
        total = sum(contagem.values())
        aviso = "" if n == total else f"  (majoritário: {n}/{total})"
        if remetente.aplicar_apelido(Apelido(
            camera_id=camera, data_ref=data_ref, pseudonimo=pseudonimo, apelido=apelido,
        )):
            ok += 1
            print(f"  {pseudonimo:<5} = {apelido}{aviso}")
        else:
            falhas += 1
            print(f"  {pseudonimo:<5} FALHOU (o pseudônimo existe no banco para {data_ref}?)")
    print(f"\n{ok} apelidos gravados, {falhas} falhas.")


def main() -> None:
    p = argparse.ArgumentParser(description="Gabarito de identidade para o teste de validação")
    p.add_argument("--gerar", action="store_true",
                   help="Gera o CSV a partir do índice de miniaturas")
    p.add_argument("--camera", default=None, help="Id da câmera (com --gerar)")
    p.add_argument("--data", default=None, help="AAAA-MM-DD (padrão: o último dia gravado)")
    p.add_argument("--sobrescrever", action="store_true")
    p.add_argument("--metricas", default=None, metavar="CSV", help="Mede o gabarito preenchido")
    p.add_argument("--aplicar", default=None, metavar="CSV",
                   help="Grava o apelido majoritário de cada P via API")
    args = p.parse_args()

    if args.gerar:
        if not args.camera:
            sys.exit("--gerar precisa de --camera")
        gerar(args.camera, args.data, args.sobrescrever)
    elif args.metricas:
        medir(Path(args.metricas))
    elif args.aplicar:
        aplicar(Path(args.aplicar))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
