# Resultados medidos

Medições de 25/08/2026. Máquina: Windows 11, RTX 3050 6 GB Laptop,
Python 3.11.16, torch 2.6.0+cu124, ultralytics 8.4.128.

Todas as execuções ficam gravadas na tabela `execucao` com modelo, limiar de
confiança, fonte e hash do commit. `curl http://127.0.0.1:8000/execucoes`.

---

## 1. Contra anotação humana (MOT17-09)

**Sequência:** MOT17-09, 525 quadros a 30 fps, 1920×1080, câmera fixa e baixa
numa calçada comercial movimentada. 26 pessoas anotadas.
Linha vertical em `x = 1385`, cruzada por 20 das 26 trajetórias, em calçada
aberta (conferido no quadro 250 — sem pilar nem poste sobre a linha).

**Método:** as trajetórias anotadas passam pela **mesma** `LinhaDeContagem`, com
os mesmos limiares de histerese, cooldown e idade mínima. Só uma variável muda
entre a referência e a medição: a qualidade da detecção e do rastreio.

### O erro depende de quanto a pessoa estava visível

O MOT17 anota pessoas mesmo quando estão quase inteiramente atrás de outras. A
coluna de visibilidade permite perguntar de quem o sistema deveria dar conta.

| visibilidade mínima na referência | referência | medido | erro | viés |
|---|---|---|---|---|
| 0% — tudo que foi anotado | 16 | 11 | 31,2% | −5 |
| **25%** | 10 | 11 | **10,0%** | +1 |
| 50% | 9 | 11 | 22,2% | +2 |
| 75% | 8 | 11 | 37,5% | +3 |

Saídas: 3 contra 3, erro 0%, em todos os cortes.

**O que isso quer dizer.** O viés muda de sinal entre 0% e 25%: abaixo disso o
sistema perde gente, acima ele conta a mais. A população que ele efetivamente
enxerga fica em torno de um quarto a metade de visibilidade — abaixo disso a
pessoa está tapada por outra e nenhum detector a encontra.

**Não estamos escolhendo o 25% por ele passar na meta.** O número honesto a
levar adiante é que **acurácia sem declarar o corte de visibilidade não
significa nada em cena aglomerada**. Numa porta de faculdade a oclusão é muito
menor que numa calçada comercial de Sydney em hora de pico, então estes valores
são um limite pessimista, não uma previsão.

### Modelo maior piora, e isso é informação

| modelo | medido | referência (vis. 0%) | erro | quadros/s |
|---|---|---|---|---|
| yolo11n | 11 | 16 | 31,2% | 39,3 |
| yolo11s | 10 | 16 | 37,5% | 20,0 |
| yolo11m | 9 | 16 | 43,8% | 19,1 |

Se detecção fosse o gargalo, o modelo maior teria melhorado. Ele piorou —
sinal de que o que falta **não é enxergar melhor, é enxergar quem está atrás de
outra pessoa**, e nenhum tamanho de rede resolve oclusão total. Confirma a
leitura da tabela de visibilidade por outro caminho.

Decisão: fica o **yolo11n**, que é o mais preciso aqui e o dobro mais rápido.

---

## 2. Contra a linha de base (subtração de fundo)

O detector é o **único** componente trocado — linha, histerese, cooldown e
direção são idênticos. Sem isso a diferença não teria explicação única.

### MOT17-09

| método | entradas | referência | erro | quadros/s |
|---|---|---|---|---|
| YOLO11n + ByteTrack | 11 | 16 | **31,2%** | 39,3 |
| MOG2 + vizinho próximo | 5 | 16 | 68,8% | 17,4 |

O YOLO acha **mais que o dobro** das travessias, e ainda por cima mais rápido —
porque roda na GPU enquanto a subtração de fundo é trabalho de CPU.

### Vídeo de sala (people-detection.mp4, Intel)

| método | entradas | saídas | total | quadros/s |
|---|---|---|---|---|
| YOLO11n + ByteTrack | 1 | 2 | 3 | 70,0 |
| MOG2 + vizinho próximo | 1 | 1 | 2 | 110,6 |

Cena com fundo estático, luz constante e pessoas isoladas — **o caso mais
favorável possível para subtração de fundo**, e ainda assim ela perde uma
travessia. É o argumento por que "usei YOLO" virou "escolhi YOLO".

---

## 3. Desempenho

| cenário | quadros/s |
|---|---|
| Uma câmera, GPU, 768×432 | 70,0 |
| Uma câmera, GPU, 1920×1080 | 39,3 |
| Uma câmera, CPU, 768×432 | 10,9 |
| **Duas câmeras, ambas na GPU** | **0,2** |
| Duas câmeras, uma GPU + uma CPU | 12,4 e 10,9 |

**Dois processos YOLO na mesma GPU são inviáveis no Windows.** Caem para ~5
segundos por quadro cada — 350 vezes mais lento que um processo sozinho. A causa
é o driver WDDM alternando contextos CUDA entre processos.

Isto **não afeta o desenho de produção**, em que cada agente roda ao lado da sua
própria câmera, em máquina separada. Afeta quem testar as duas localmente: use
`--dispositivo cpu` na segunda.

---

## 4. Duas câmeras ao mesmo tempo

Dois agentes, um serviço, um banco. `entrada_a` na GPU, `entrada_b` na CPU.

| | eventos | gravados | em fila |
|---|---|---|---|
| entrada_a | 1 entrada, 2 saídas | 3 | 0 |
| entrada_b | 5 entradas | 5 | 0 |

Nenhum erro de escrita concorrente. O desenho já previa isso — quem escreve no
banco é só o serviço, e o WAL está ligado — mas agora está exercido com dois
produtores de verdade.

---

## 5. Resiliência

| teste | resultado |
|---|---|
| Serviço fora do ar durante a contagem | 3 eventos para a fila local, 0 perdidos |
| Serviço volta | fila drenada sozinha na execução seguinte |
| Mesmo lote reenviado (21.218 eventos) | 0 gravados, 21.218 reconhecidos como duplicados |

---

## 6. Limitações conhecidas

Declaradas, não escondidas. Cada uma tem um teste que a trava em
`tests/test_linha.py`.

1. **Oclusão total não é recuperável.** É o maior custo medido, e a tabela de
   visibilidade quantifica quanto.
2. **Linha atrás de oclusor perde travessia.** Aconteceu no primeiro teste
   deste projeto: a linha caiu sobre um pilar, uma pessoa foi ocluída ao
   atravessar, o track quebrou e o cruzamento sumiu. Movê-la resolveu. Virou a
   primeira regra de `docs/calibracao.md`.
3. **Track que nasce dentro da zona morta não conta.** Quem aparece pela
   primeira vez em cima da linha nunca foi visto de um dos lados.
4. **Cooldown de 1,5 s engole ida-e-volta legítima.** Quem realmente entra e
   sai em menos de um segundo e meio conta uma vez. Escolha deliberada: quem
   hesita na porta é muito mais comum que quem faz isso de verdade.
5. **Idade mínima de 3 quadros descarta passagem relâmpago.** Elimina falso
   positivo de um quadro só; o preço é perder quem cruza em dois quadros.

---

## 7. O que estes números não respondem

Nada aqui foi medido na porta da faculdade. Geometria, iluminação, contraluz e
comportamento de quem entra num prédio de aula são diferentes de uma calçada
comercial australiana.

**A meta declarada — erro ≤ 10% em cada direção — só pode ser verificada com a
contagem manual descrita em `docs/avaliacao.md`**, feita por duas pessoas sobre
uma gravação real das duas entradas. A máquina que consome esse CSV está pronta
e testada:

```bash
python scripts/avaliar.py --camera entrada_a --ground-truth dados/ground_truth/porta.csv
```

O que falta é a gravação, e ela depende de autorização da coordenação.
