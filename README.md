# Limiar

Contagem de fluxo de pessoas nas entradas da faculdade a partir de vídeo.

O sistema registra **porta, instante e direção**. Não há imagem, não há rosto e
não há vínculo com identidade civil em nenhum ponto — ver `PROJETO.txt`, seção 16.

- `PROJETO.txt` — documento de projeto: escopo, decisões justificadas e as 111
  micro-etapas com critério de aceite.
- `deck.html` — apresentação em 19 slides (abre direto no navegador).

## Instalar

```bash
uv sync
python scripts/criar_banco.py
```

O banco vai para `~/Documents/dados-fluxo/fluxo.db`, **fora do OneDrive**:
sincronização em nuvem durante escrita corrompe SQLite. O caminho vem de
`CAMINHO_BANCO` no `.env` (copie de `.env.exemplo`).

## Rodar

```bash
# serviço central — documentação interativa em http://127.0.0.1:8000/docs
python scripts/rodar_servico.py

# popular com 14 dias sintéticos, para desenvolver sem câmera
python scripts/simular_dia.py --dias 14

# testes (sem rede, sem GPU, sem vídeo)
python -m pytest
```

Os dados sintéticos entram com `origem=SINTETICO`. Toda consulta de resultado
filtra `VISAO` por padrão, então dado de simulação nunca vaza para um número de
relatório — para vê-los, passe `?origem=SINTETICO`.

## Estado

| Fase | O que é | Estado |
|---|---|---|
| 0 | Ambiente, estrutura, configuração | pronto |
| 1 | Banco e persistência | pronto |
| 2 | Modelo do evento e serviço HTTP | pronto |
| 3 | Simulador de eventos sintéticos | pronto |
| 4–5 | Detecção e rastreamento | pendente |
| 6 | Contagem por linha virtual | pendente |
| 7 | Agente com fila local | pendente |
| 8 | Análise e painel | pendente |
| 9 | Avaliação contra contagem manual | pendente |

## Notas de ambiente

**O projeto não é instalado como pacote.** O repositório vive dentro do
OneDrive, e o cache de hardlinks do `uv` é incompatível com o filtro de
sincronização da nuvem (`os error 396`) — qualquer build falha de forma
intermitente. Em vez disso, `src` entra no `sys.path`: o pytest pela chave
`pythonpath` do `pyproject.toml`, e cada script por três linhas no topo.

**A visão computacional é um extra opcional**, porque pesa ~2,5 GB com o
PyTorch e só é necessária a partir da fase 4:

```bash
uv sync --extra visao
```
