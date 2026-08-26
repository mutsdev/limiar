# Limiar

Contagem de fluxo de pessoas nas entradas da faculdade a partir de vídeo.

O sistema registra **porta, instante e direção**. Não há imagem, não há rosto e
não há vínculo com identidade civil em nenhum ponto.

| documento | o que é |
|---|---|
| `PROJETO.txt` | escopo, decisões justificadas, 111 micro-etapas com critério de aceite |
| `deck.html` | apresentação em 19 slides (abre direto no navegador) |
| `docs/arquitetura.md` | camadas, idempotência, e as regras que não se quebram |
| `docs/calibracao.md` | onde montar a câmera e onde desenhar a linha |
| `docs/avaliacao.md` | como se prova que o número está certo |

## Instalar

```bash
uv sync                  # núcleo: banco, serviço, painel, testes
uv sync --extra visao    # + YOLO/PyTorch (~2,5 GB), necessário da fase 4 em diante
python scripts/criar_banco.py
```

O banco vai para `~/Documents/dados-fluxo/fluxo.db`, **fora do OneDrive**:
sincronização em nuvem durante escrita corrompe SQLite. O caminho vem de
`CAMINHO_BANCO` no `.env` (copie de `.env.exemplo`).

## Rodar

```bash
# serviço central — documentação interativa em http://127.0.0.1:8000/docs
python scripts/rodar_servico.py

# painel web em http://127.0.0.1:8501
python scripts/rodar_painel.py

# contar num vídeo, gravando o vídeo anotado
python scripts/processar_video.py --camera entrada_a --sem-envio --anotar

# contar e entregar ao serviço
python scripts/processar_video.py --camera entrada_a

# desenhar a linha de contagem clicando no quadro
python scripts/calibrar_linha.py --camera entrada_a --fonte dados/videos/porta.mp4

# popular com 14 dias sintéticos, para desenvolver sem câmera
python scripts/simular_dia.py --dias 14

# YOLO contra a linha de base de subtração de fundo
python scripts/comparar_detectores.py --camera entrada_a

# 146 testes: sem rede, sem GPU, sem vídeo
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
| 9 | Avaliação e linha de base | máquina pronta; **falta a contagem manual** |
| — | Gravação da porta real e calibração | **depende de autorização** |
| — | Etapa 2: re-identificação | não iniciada |

O que falta para fechar a etapa "Uno" não é código: é a gravação das duas
entradas e a contagem manual de referência. Ver `docs/avaliacao.md`.

## Ambiente

O repositório vive dentro do OneDrive, o que exige dois ajustes já fixados no
`pyproject.toml` (`package = false` e `link-mode = "copy"`) — o cache de
hardlinks do `uv` é incompatível com o filtro de sincronização da nuvem. Para
não sincronizar os 2,5 GB do PyTorch, o ambiente virtual mora fora:

```bash
export UV_PROJECT_ENVIRONMENT="C:/Users/joaop/Documents/dados-fluxo/.venv-limiar"
```

Numa máquina sem OneDrive nada disso é necessário: `uv sync` basta.

## Vídeo de amostra

`dados/videos/people-detection.mp4` vem dos vídeos de exemplo da Intel
(`intel-iot-devkit/sample-videos`, Apache-2.0). Serve para provar que o
software funciona; **não serve para calibrar** — o ângulo, a iluminação e o
comportamento não são os da porta real.
