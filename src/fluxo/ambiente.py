"""Faz o script rodar no ambiente certo, sem o usuário ter que saber disso.

O `python` do PATH desta máquina não é o do projeto — as dependências pesadas
moram num ambiente virtual fora do OneDrive. Em vez de exigir que quem usa
lembre de exportar `UV_PROJECT_ENVIRONMENT` antes de cada comando, o script se
reexecuta sozinho no interpretador correto.

Só depende da biblioteca padrão: precisa funcionar *antes* de qualquer import
que exija o ambiente montado.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Ordem de procura. A primeira que existir vence.
CANDIDATOS = (
    RAIZ / ".venv",                                        # instalação padrão
    Path.home() / "Documents" / "dados-fluxo" / ".venv-limiar",  # esta máquina
)


def _executavel(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _tem_visao(venv: Path) -> bool:
    """O ambiente tem o extra `visao` instalado?

    Um ambiente só com o núcleo roda os testes, mas não abre vídeo. Escolher
    ele para um script de visão daria `ModuleNotFoundError: cv2` depois de
    trocar de interpretador — erro confuso, longe da causa.
    """
    libs = venv / ("Lib/site-packages" if os.name == "nt" else "lib")
    return any(libs.glob("cv2*")) or any(libs.glob("*/cv2*"))


def ambiente_do_projeto(exigir_visao: bool = False) -> Path | None:
    """O ambiente virtual a usar, ou None se nenhum servir."""
    escolhido = os.environ.get("UV_PROJECT_ENVIRONMENT", "").strip()
    if escolhido:
        caminho = Path(escolhido).expanduser()
        return caminho if _executavel(caminho).exists() else None

    existentes = [c for c in CANDIDATOS if _executavel(c).exists()]
    if not existentes:
        return None
    if exigir_visao:
        com_visao = [c for c in existentes if _tem_visao(c)]
        if com_visao:
            return com_visao[0]
    return existentes[0]


def garantir_venv(exigir_visao: bool = True) -> None:
    """Reexecuta o processo no interpretador do projeto, se não estiver nele.

    Silencioso quando já está certo. Se não houver ambiente montado, não faz
    nada e deixa o erro de import acontecer — ele diz o que instalar, e é mais
    útil que uma mensagem inventada aqui.
    """
    # Marca de reentrada: sem ela, um ambiente quebrado viraria laço infinito.
    if os.environ.get("_LIMIAR_REEXEC") == "1":
        return

    venv = ambiente_do_projeto(exigir_visao)
    if venv is None:
        return

    executavel = _executavel(venv)
    try:
        ja_estamos = executavel.resolve() == Path(sys.executable).resolve()
    except OSError:
        ja_estamos = False
    if ja_estamos:
        return

    os.environ["_LIMIAR_REEXEC"] = "1"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.execv(str(executavel), [str(executavel), *sys.argv])


def e_webcam(alvo: str | int | Path | None) -> bool:
    """O alvo é um índice de webcam?

    Só dígitos puros contam. `"0"` é webcam; `"0.mp4"` e `"01_entrada.mp4"` são
    arquivos — e essa distinção não é teórica, porque os vídeos deste projeto se
    chamam exatamente `01_`, `02_`, `03_`.
    """
    if isinstance(alvo, int):
        return True
    return isinstance(alvo, str) and alvo.isdigit()


def normalizar_fonte(alvo: str | int | Path) -> str | int:
    """Converte o que veio da linha de comando na fonte que o OpenCV entende.

    `cv2.VideoCapture` distingue os dois casos pelo TIPO, não pelo valor:
    inteiro é dispositivo de captura, texto é caminho ou URL. Passar `"0"` como
    texto faz ele procurar um arquivo chamado `0` e falhar com uma mensagem que
    não parece ter nada a ver com webcam.
    """
    if e_webcam(alvo):
        return int(alvo)
    return alvo if isinstance(alvo, str) else str(alvo)


def id_de_camera(caminho: str | Path) -> str:
    """Nome de câmera a partir do arquivo de vídeo, ou do índice da webcam.

    Serve para `python scripts/calibrar_linha.py video.mp4` funcionar sem
    obrigar a inventar um identificador antes de ver o resultado.

    O resultado é ASCII puro: o id vira nome de arquivo (prévia da linha,
    vídeo anotado, fila local) e chave de YAML. Acento em nome de arquivo
    funciona no Windows, mas atravessa console em cp1252 e volta corrompido —
    já aconteceu duas vezes neste projeto.
    """
    import unicodedata

    # Uma câmera chamada "0" no YAML não diz nada a quem abrir o arquivo depois.
    if e_webcam(caminho):
        indice = int(caminho)
        return "webcam" if indice == 0 else f"webcam_{indice}"

    bruto = Path(str(caminho)).stem.lower()
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", bruto) if not unicodedata.combining(c)
    )
    limpo = "".join(c if c.isascii() and c.isalnum() else "_" for c in sem_acento)
    limpo = limpo.strip("_")
    while "__" in limpo:
        limpo = limpo.replace("__", "_")
    return limpo[:48] or "camera"
