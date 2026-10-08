# A geometria do Limiar

Material de estudo sobre a parte matemática do **Limiar**, o contador de fluxo de pessoas da entrada da faculdade. Feito para quem quer entender como o sistema decide "entrou" ou "saiu" sem precisar ler o projeto inteiro.

## O que é o Limiar, em cinco linhas

Uma câmera na porta manda quadros para um computador. Um detector pronto (YOLO) desenha um retângulo em volta de cada pessoa; um rastreador pronto (ByteTrack) dá a cada retângulo um número que persiste entre quadros. A partir daí, um módulo pequeno, escrito para o projeto e sem nenhuma biblioteca numérica, olha o pé de cada retângulo e decide se ele cruzou uma linha desenhada no chão, e em que direção. O sistema guarda só porta, instante e direção. Não guarda imagem.

Este material é sobre esse módulo pequeno. A decisão inteira cabe em duas ideias: o **sinal** de um produto vetorial diz de que lado da linha o pé está; o **módulo** diz a que distância.

## Como ler

1. **`apostila.pdf`** (ou `apostila.md`): o texto. Nove capítulos, do dado cru até a decisão, com um exemplo numérico e o Python correspondente em cada um.
2. **`geometria.py`** e **`contador.py`**: as funções e a máquina de estados, isoladas e comentadas. São cópias didáticas do código de produção, com os mesmos nomes.
3. **`exemplos.py`**: os exemplos da apostila, prontos para rodar. Os vetores estão no topo do arquivo para serem trocados.
4. **`demo.py`**: roda o contador sobre uma trajetória real e gera a tabela quadro a quadro e as seis figuras.

## Como rodar

Só Python 3.11 ou mais novo. `matplotlib` só para as figuras.

```bash
python exemplos.py          # os números da apostila
python demo.py              # tabela quadro a quadro + figuras/
python demo.py --conferir   # compara com o código de produção (precisa do repositório do Limiar)
python gerar_pdf.py         # apostila.md -> apostila.pdf (Windows, usa o Edge instalado)
```

## Os dados

`pessoa1.csv` são 52 quadros de uma pessoa cruzando a entrada em 3 de setembro de 2026: número do quadro, instante, os quatro cantos do retângulo e a confiança do detector. `intervalos_ms.csv` são os intervalos entre quadros consecutivos da gravação inteira. **Só coordenadas e instantes**; não há imagem, nome nem qualquer outro dado nos arquivos. A gravação original não é distribuída.

## Arquivos

| Arquivo | O que é |
|---|---|
| `apostila.md`, `apostila.pdf` | O texto |
| `figuras/f1.png` … `f6.png` | As figuras, geradas por `demo.py` |
| `geometria.py` | `produto_vetorial`, `lado`, `distancia_ponto_reta`, `segmentos_se_cruzam`, `ponto_base` |
| `contador.py` | `Contador.passo(quadro, t, caixa)`: a máquina de estados, um passo por quadro |
| `exemplos.py` | Os exemplos da apostila |
| `demo.py` | Tabela, figuras e verificação contra produção |
| `extrair_csv.py` | Como os CSV foram extraídos da gravação (roda só com a gravação presente) |
| `gerar_pdf.py` | Markdown para PDF |

## Onde está o código de produção

No repositório do Limiar: `src/fluxo/contagem/geometria.py` (as funções), `src/fluxo/contagem/linha.py` (a máquina de estados), `config/pipeline.yaml` (os limiares) e `config/cameras.yaml` (a linha de cada câmera). O capítulo 9 da apostila tem o mapa completo. `python demo.py --conferir` prova que a cópia didática e a produção dão o mesmo resultado nos mesmos casos.
