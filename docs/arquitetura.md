# Arquitetura

## Camadas

A dependência só aponta para baixo. Nunca o contrário.

```
scripts/            entrypoints finos: argumentos e uma chamada
   |
   v
agente/  servico/   orquestração e transporte
   |
   v
visao/              OpenCV e ultralytics vivem SÓ aqui
   |
   v
contagem/           geometria pura: sem numpy, sem cv2
   |
   v
dominio/            evento e rastro; sem infraestrutura
```

**Por que `contagem` não pode importar numpy:** é o componente que decide se
alguém passou — o mais crítico do sistema. Mantê-lo em Python puro permite
provar seu comportamento com dezenas de casos em milissegundos, sem GPU, sem
modelo e sem vídeo. Instalar a camada de visão custa 2,5 GB; o núcleo continua
testável sem ela.

**Por que `Rastro` mora em `dominio` e não em `visao`:** `contagem` precisa
dele e não pode depender de `visao`. Uma pessoa sendo acompanhada é conceito do
problema, não da biblioteca.

## Dois processos

O agente processa o vídeo e produz eventos; o serviço recebe e grava. No local
eles estarão em máquinas diferentes — a câmera na porta, o banco no servidor.
Nascer monolítico significaria reescrever na hora de instalar.

A separação também permitiu construir o painel inteiro com dados sintéticos,
antes de a visão computacional existir.

```
câmera A ─→ agente A ─┐
                      ├─ HTTP POST /eventos/lote ─→ serviço ─→ SQLite ─→ painel
câmera B ─→ agente B ─┘
```

## Idempotência

Cada evento carrega `id_evento`, derivado de forma determinística de
`(câmera, track, direção, segundo)`. A coluna é `UNIQUE`.

Sem isso, uma queda de rede seguida de reenvio infla a contagem — **e o erro é
silencioso**, porque o número continua parecendo plausível. É a razão de o
reenvio ser seguro e, portanto, de a fila local poder existir.

## A fila local

Quando o serviço não responde, o agente grava em JSONL e segue contando. Na
execução seguinte, drena antes de começar.

JSONL e não JSON único: uma queda no meio da escrita corrompe no máximo a
última linha, e as anteriores continuam legíveis.

## Origem do dado

A coluna `origem` separa `VISAO` de `SINTETICO`. **Toda consulta de resultado
filtra `VISAO` por padrão** — ver dado de simulação exige pedir. É o que
permite desenvolver e demonstrar o painel com dados falsos sem risco de eles
virarem número de relatório.

## Regras que não se quebram

1. **Nenhum caminho relativo, nenhum `os.chdir()`.** Todo caminho sai de
   `config.py`, absoluto. Caminho relativo quebra quando o script é chamado de
   outra pasta, e o bug é difícil de achar.
2. **O banco fica fora de pasta sincronizada em nuvem.** Sincronização
   concorrente corrompe SQLite.
3. **Scripts são finos.** Lógica mora no pacote, para poder ser testada.
4. **`dados/` nunca entra no git.** É imagem de pessoa real.
5. **Nenhuma coluna identifica pessoa.** Não é lacuna a preencher depois; é a
   definição do sistema.

## Notas de ambiente desta máquina

O repositório vive dentro do OneDrive, e o cache de hardlinks do `uv` colide
com o filtro de sincronização da nuvem (`os error 396`). Duas consequências,
ambas fixadas no `pyproject.toml`:

- `package = false` — o projeto não é construído nem instalado; `src` entra no
  `sys.path` (pytest pela chave `pythonpath`, scripts por três linhas no topo).
- `link-mode = "copy"` — o `uv` copia em vez de criar hardlink.

O ambiente virtual mora **fora** do OneDrive, para não sincronizar os 2,5 GB do
PyTorch:

```bash
export UV_PROJECT_ENVIRONMENT="C:/Users/joaop/Documents/dados-fluxo/.venv-limiar"
```

Numa máquina sem OneDrive, nada disso é necessário e `uv sync` basta.

## Como crescer

A etapa 2 (re-identificação) entra como `reid/` e `ocupacao/`, irmãos de
`contagem/`, consumindo `dominio` e sendo consumidos por `agente`. Nenhuma
camada existente muda de lugar.
