# Avaliação

Um contador que não é avaliado é uma opinião com interface. A avaliação é parte
do entregável.

## Meta declarada

Erro absoluto percentual **menor ou igual a 10%, em cada direção
separadamente**, num trecho de 15 minutos em horário movimentado.

Cada direção separadamente, e não na média: uma direção costuma ser mais
ocluída que a outra, e a média esconderia isso.

## Contagem manual

É a única referência válida, e **não pode ser produzida pelo próprio sistema** —
seria circular.

1. Escolha um trecho de 15 minutos em horário movimentado.
2. **Duas pessoas contam de forma independente**, assistindo ao vídeo.
3. Se divergirem mais de 3%, assistam juntas e reconciliem.
4. Registre em `dados/ground_truth/<video>.csv`, **por minuto**:

```csv
minuto,entradas,saidas
0,12,3
1,9,5
```

Por minuto, e não só o total, porque totais batem por compensação: uma contagem
a mais no minuto 2 e uma a menos no minuto 9 dão um total perfeito e escondem
dois erros. É o que a métrica `mae_por_janela` mede.

## Três regimes, medidos separadamente

Uma média única esconde o comportamento do sistema:

- **fluxo baixo** — pessoas isoladas
- **fluxo médio**
- **fluxo de pico** — grupos, oclusão, pessoas lado a lado

O erro no pico é o número que importa, e vai ser o pior.

## Linha de base

```bash
python scripts/comparar_detectores.py --camera entrada_a
```

Roda YOLO11+ByteTrack e MOG2+vizinho-próximo sobre o mesmo vídeo, com a mesma
linha, a mesma histerese e o mesmo cooldown. **O detector é o único componente
trocado** — sem isso a diferença não teria explicação única.

É o que transforma "usei YOLO" em "escolhi YOLO, e aqui está o número".

### Resultado no vídeo de amostra (25/08/2026)

Vídeo público da Intel, 596 quadros, sala com poucas pessoas atravessando.

| método | dispositivo | entradas | saídas | total | q/s |
|---|---|---|---|---|---|
| YOLO11n + ByteTrack | GPU | 1 | 2 | 3 | 70 |
| MOG2 + vizinho próximo | CPU | 1 | 1 | 2 | 111 |

O MOG2 perdeu uma passagem — e **esta é a cena mais favorável possível para
ele**: fundo estático, iluminação constante, pessoas isoladas e bem separadas.
Numa entrada de faculdade em horário de pico, com grupos encostados e
iluminação mudando, a diferença tende a crescer, porque o modo de falha do MOG2
(vários corpos virando um blob só) só aparece com aglomeração.

**Este número ainda não é acurácia.** É divergência entre métodos. Saber qual
está certo exige a contagem manual descrita acima, sobre a gravação da porta
real.

## Métricas registradas

| métrica | o que responde |
|---|---|
| erro absoluto | quantas passagens de diferença |
| erro percentual | a meta dos 10% |
| viés | positivo conta demais, negativo perde passagem |
| MAE por janela | erros que se compensam no total |
| saldo do dia | verificação sem precisar de contagem manual |

## Rastreabilidade

Toda execução grava na tabela `execucao`: modelo, rastreador, limiar de
confiança, fonte e hash do commit. Seis semanas depois ainda dá para saber com
qual configuração um número foi produzido.
