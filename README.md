# Limiar

Contagem de fluxo de pessoas nas entradas da faculdade a partir de vídeo.

O sistema registra **porta, instante e direção**. Não há imagem, não há rosto e
não há vínculo com identidade civil em nenhum ponto.

| documento | o que é |
|---|---|
| `PROJETO.txt` | escopo, decisões justificadas, 111 micro-etapas com critério de aceite |
| `deck.html` | apresentação em 10 slides (abre direto no navegador) |
| `docs/arquitetura.md` | camadas, idempotência, e as regras que não se quebram |
| `docs/calibracao.md` | onde montar a câmera e onde desenhar a linha |
| `docs/avaliacao.md` | como se prova que o número está certo |
| `docs/resultados.md` | **os números medidos**, com as limitações declaradas |

## Começar

Quatro comandos, numa máquina limpa. **Não precisa de GPU nem de vídeo** — o
simulador povoa o banco com dados sintéticos e o painel abre com as curvas.

```bash
uv sync
python scripts/criar_banco.py
python scripts/simular_dia.py --dias 14
python scripts/rodar_painel.py          # http://127.0.0.1:8501
```

Para rodar os testes: `python -m pytest` (224, sem rede, sem GPU, sem vídeo).

### E para trabalhar com vídeo de verdade

```bash
uv sync --extra visao    # + YOLO e PyTorch, ~2,5 GB
```

Em Windows e Linux vêm as wheels CUDA; em macOS, as normais do PyPI. Sem placa
NVIDIA tudo funciona em CPU, mais devagar (~11 quadros/s em 768×432).

O banco vai para `~/Documents/dados-fluxo/fluxo.db` — **fora do repositório de
propósito**, porque sincronização em nuvem durante a escrita corrompe SQLite.
Para mudar, copie `.env.exemplo` para `.env` e ajuste `CAMINHO_BANCO`.

### O que não está aqui

`dados/` nunca é versionado: é vídeo de pessoas reais. Os vídeos de exemplo e as
sequências de avaliação vêm por script (`scripts/baixar_mot.py`) e têm licença
própria — o MOT17 é **CC BY-NC-SA 3.0, uso não comercial**. Ver "Dados de
terceiros" no fim deste arquivo.

## Rodar

```bash
# serviço central — documentação interativa em http://127.0.0.1:8000/docs
python scripts/rodar_servico.py

# painel web em http://127.0.0.1:8501
python scripts/rodar_painel.py

# testar um vídeo qualquer: marque a linha e a contagem roda na hora
python scripts/calibrar_linha.py "C:/Users/voce/Videos/porta.mp4"

#   na janela: q sai, espaço pausa
#   --sem-conferir só grava a linha, para calibrar vários de uma vez

# a mesma coisa sem clicar: o rastreador propõe a linha
python scripts/calibrar_linha.py "C:/Users/voce/Videos/porta.mp4" --sugerir

# a webcam desta máquina, para ver a contagem acontecer ao vivo
python scripts/calibrar_linha.py --listar-cameras
python scripts/calibrar_linha.py 0
python scripts/processar_video.py webcam --sem-envio

# depois, o vídeo inteiro
python scripts/processar_video.py porta --sem-envio --ao-vivo
#   --escala 1.5 aumenta, --velocidade 2 acelera, --anotar também grava

# contar e entregar ao serviço
python scripts/processar_video.py entrada_a

# popular com 14 dias sintéticos, para desenvolver sem câmera
python scripts/simular_dia.py --dias 14

# YOLO contra a linha de base de subtração de fundo
python scripts/comparar_detectores.py --camera entrada_a

# avaliar contra anotação humana (MOT17)
python scripts/baixar_mot.py --sequencias MOT17-09
python scripts/avaliar.py --mot dados/videos/MOT17-09 --sugerir-linha
python scripts/avaliar.py --mot dados/videos/MOT17-09 --camera mot17_09 --visibilidade 0.25

# avaliar contra contagem manual, quando a gravação real existir
python scripts/avaliar.py --camera entrada_a --ground-truth dados/ground_truth/porta.csv

# calibrar por medição: a visão roda UMA vez e grava o que enxergou;
# a contagem recorre a trilha quantas vezes for preciso, sem GPU
python scripts/processar_video.py entrada_a --sem-envio --gravar-trilhas
python scripts/reprocessar.py entrada_a --varredura

# 224 testes: sem rede, sem GPU, sem vídeo
python -m pytest
```

Os dados sintéticos entram com `origem=SINTETICO`, e toda consulta de resultado
filtra `VISAO` por padrão — dado de simulação nunca vira número de relatório
por descuido.

## Estado

| Fase | O que é | Estado |
|---|---|---|
| 0 | Ambiente, estrutura, configuração | pronto |
| 1 | Banco e persistência | pronto |
| 2 | Modelo do evento e serviço HTTP | pronto |
| 3 | Simulador de eventos sintéticos | pronto |
| 4 | Detecção (YOLO11, GPU) | pronto |
| 5 | Rastreamento (ByteTrack) | pronto |
| 6 | Contagem por linha virtual | pronto |
| 7 | Agente com fila local | pronto |
| 8 | Análise e painel | pronto |
| 9 | Avaliação e linha de base | pronto — ver `docs/resultados.md` |
| 10 | Empacotamento e documentação | pronto |
| 11 | Trilhas: recontar sem GPU | pronto — `docs/resultados.md` §8 |
| — | Gravação da porta real e calibração | **depende de autorização** |
| — | Etapa 2: re-identificação | não iniciada |

O que falta para fechar a etapa "Uno" não é código: é a gravação das duas
entradas e a contagem manual de referência. Ver `docs/avaliacao.md`.

Quando ela existir, a calibração da porta real é medição e não palpite: grave a
trilha uma vez e rode `scripts/reprocessar.py <camera> --varredura`. Foi assim
que a costura de rastro quebrado — construída para tratar oclusão no batente da
porta — acabou **desligada por medição**, e não por precaução (`§2b`).

## Ambiente

**Na maioria das máquinas, `uv sync` basta e esta seção não interessa.**

Ela vale para quem clonar o repositório **dentro de uma pasta sincronizada em
nuvem** (OneDrive, Google Drive, Dropbox). Ali o cache de hardlinks do `uv`
colide com o filtro de sincronização e a instalação falha de forma intermitente
(`os error 396`). Dois ajustes no `pyproject.toml` já resolvem isso para todos —
`package = false` e `link-mode = "copy"` — e não atrapalham quem está fora.

Falta só tirar o ambiente virtual de dentro da pasta sincronizada, para não
subir 2,5 GB de PyTorch para a nuvem:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/Documents/dados-fluxo/.venv-limiar"
```

**Não é preciso exportar nada para usar os scripts.** Eles detectam o ambiente
do projeto e se reexecutam nele — `python scripts/processar_video.py elevada`
funciona com o `python` do PATH, seja ele qual for. Entre um ambiente só com o
núcleo e um com o extra `visao`, escolhem o segundo.

## Duas câmeras na mesma máquina

Dois processos YOLO na mesma GPU são inviáveis no Windows: caem para ~5 s por
quadro cada, porque o driver WDDM alterna contextos CUDA entre processos. Rode
a segunda em CPU:

```bash
python scripts/processar_video.py --camera entrada_a --dispositivo 0
python scripts/processar_video.py --camera entrada_b --dispositivo cpu
```

Não afeta a instalação real, em que cada agente fica ao lado da sua câmera, em
máquina separada.

## Dados de terceiros

Nenhum é versionado — `dados/` fica fora do git.

| origem | licença | para quê |
|---|---|---|
| `intel-iot-devkit/sample-videos` | Apache-2.0 | provar que o software funciona |
| MOT17 (espelho no HuggingFace) | CC BY-NC-SA 3.0, uso não comercial | avaliar contra anotação humana |

**Nenhum deles serve para calibrar.** Ângulo, iluminação e comportamento não
são os da porta real — ver `docs/calibracao.md`.

O site oficial do MOTChallenge está inacessível desta rede; `scripts/baixar_mot.py`
usa um espelho. Cite o MOTChallenge no relatório, não o espelho.

## Licença

O **código** deste repositório é MIT — ver `LICENSE`.

A licença **não** se estende aos conjuntos de dados da tabela acima, que não são
distribuídos aqui e têm termos próprios. O MOT17, em particular, é
CC BY-NC-SA 3.0 e **proíbe uso comercial**.
