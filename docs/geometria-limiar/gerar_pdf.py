"""Converte ``apostila.md`` em ``apostila.pdf``.

Markdown -> HTML com a biblioteca ``markdown``; HTML -> PDF com o Microsoft
Edge em modo headless, que já vem no Windows. Nada de MathJax: as fórmulas
da apostila são texto puro.

    python gerar_pdf.py
"""

import subprocess
import sys
from pathlib import Path

import markdown

AQUI = Path(__file__).resolve().parent
MD = AQUI / "apostila.md"
HTML = AQUI / "apostila.html"
PDF = AQUI / "apostila.pdf"
EDGE = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: Georgia, "Times New Roman", serif; font-size: 11pt; line-height: 1.45;
       color: #222; max-width: 100%; margin: 0; }
h1 { font-size: 24pt; margin-bottom: 0; }
h1 + h3 { margin-top: 4pt; font-weight: normal; color: #555; font-size: 13pt; }
h2 { font-size: 16pt; margin-top: 28pt; border-bottom: 1px solid #bbb; padding-bottom: 3pt;
     page-break-after: avoid; }
h3 { font-size: 12.5pt; margin-top: 18pt; page-break-after: avoid; }
p, li { text-align: justify; }
code, pre { font-family: Consolas, "Courier New", monospace; font-size: 9pt; }
pre { background: #f4f4f4; border: 1px solid #ddd; padding: 6pt 8pt; white-space: pre-wrap;
      page-break-inside: avoid; }
code { background: #f4f4f4; padding: 0 2pt; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; font-size: 8.5pt; margin: 8pt 0; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 2pt 5pt; text-align: left; white-space: nowrap; }
th { background: #eee; }
img { max-width: 100%; display: block; margin: 8pt auto; page-break-inside: avoid; }
em { color: #444; }
hr { border: none; border-top: 1px solid #ccc; margin: 20pt 0; }
"""


def main() -> None:
    texto = MD.read_text(encoding="utf-8")
    corpo = markdown.markdown(texto, extensions=["tables", "fenced_code"])
    HTML.write_text(
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<title>A geometria do Limiar</title><style>{CSS}</style></head>"
        f"<body>{corpo}</body></html>",
        encoding="utf-8",
    )
    edge = next((e for e in EDGE if e.exists()), None)
    if edge is None:
        print(f"HTML gerado em {HTML.name}; Edge não encontrado, imprima o HTML em PDF pelo navegador.")
        return
    subprocess.run(
        [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={PDF}",
            HTML.as_uri(),
        ],
        check=True,
        timeout=120,
    )
    print(f"{PDF.name}: {PDF.stat().st_size // 1024} KB")


if __name__ == "__main__":
    sys.exit(main())
