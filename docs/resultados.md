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

## 2b. Costura de rastro quebrado — medida, e desligada

Medição de 27/08/2026.

**A hipótese.** Os três números da seção 1 apontavam para o mesmo suspeito: o
viés de −5 (perde travessia), 1,38 cruzamento por pessoa no vídeo elevado (conta
duas vezes) e o modelo maior piorando (o gargalo não é enxergar). Todos são
explicáveis por **fragmentação de track**: o rastreador encerra o track quando a
pessoa é ocluída e abre outro com id novo. O fragmento novo nasce sem lado
confirmado — e a travessia some — ou nasce sem o `contou_em` do antigo — e o
cooldown não segura a segunda contagem.

**O mecanismo.** `LinhaDeContagem` passou a poder adotar o estado de um track
recém-morto quando um id novo aparece perto dele, sob três condições: lacuna de
no máximo `costura_quadros`, distância de no máximo `costura_raio_px`, e cada
órfão adotado **uma única vez**. As duas primeiras impedem fundir duas pessoas
que se cruzam; a terceira impede que um mesmo órfão seja herdado em série.

### O que a medição disse

Com as trilhas gravadas (seção 8), a mesma visão foi recontada sob dez
combinações de parâmetros. Só a contagem muda entre as linhas da tabela.

**MOT17-09** — a costura é inerte:

| costura (quadros) | raio (px) | rastros costurados | entradas | referência | erro |
|---|---|---|---|---|---|
| 0 (desligada) | — | 0 | 11 | 16 | 31,2% |
| 15 | 80 | 14 | 11 | 16 | 31,2% |
| 30 | 160 | 34 | 12 | 16 | 25,0% |

Costurou 14 rastros e **não recuperou uma única travessia**. Faz sentido com o
que a tabela de visibilidade já dizia: o que se perde numa calçada cheia não é
track que quebra e volta, é gente que **nunca foi detectada**. Não há o que
costurar quando não há fragmento do outro lado.

**Vídeo elevado** — a costura piora:

| costura | raio | rastros costurados | entradas | saídas | \|saldo\| | cruz/pessoa |
|---|---|---|---|---|---|---|
| **0 (desligada)** | — | 0 | 11 | 11 | **0** | 1,38 |
| 15 | 80 | 15 | 10 | 14 | 4 | 1,33 |
| 30 | 160 | 19 | 10 | 15 | 5 | 1,39 |

O saldo fechava em 11/11 e passou a abrir em 4. A costura estava afirmando
travessias que **ninguém observou**: ao herdar a âncora de uma posição anterior à
lacuna, uma mudança de lado que aconteceu no escuro vira evento.

Uma variante conservadora — herdar só o `contou_em`, nunca o lado — reduz o dano
mas não o elimina (saldo 2, cruz/pessoa 1,29). Continua pior que desligada.

### A decisão

**`costura_quadros: 0` no `config/pipeline.yaml`.** O padrão acompanha a
medição, não a elegância do mecanismo.

O código e os sete testes ficam: eles provam que os dois modos de falha existem
e que a costura os corrige **isoladamente**. O que a medição mostrou é que esses
não são os modos de falha dominantes *nestes* vídeos — uma calçada aberta não
tem oclusor fixo, e é justamente o batente de porta que a costura trataria. Na
porta da faculdade a resposta pode ser outra, e agora custa um comando:

```bash
python scripts/processar_video.py <camera> --sem-envio --gravar-trilhas
python scripts/reprocessar.py <camera> --varredura
```

**O achado que sobrevive:** a hipótese da fragmentação estava errada, e o custo
medido continua sendo **oclusão total**. Isso reforça, por um terceiro caminho
independente, a mesma conclusão da seção 1 — e é um argumento a favor de montar
a câmera num ângulo que reduza oclusão, que é a decisão de hardware ainda em
aberto em `docs/calibracao.md`.

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
   primeira regra de `docs/calibracao.md`. A costura de rastro (§2b) foi
   construída para tratar isto e **medida como pior que a alternativa** nos
   vídeos disponíveis; mover a linha continua sendo a correção certa.
3. **Track que nasce dentro da zona morta não conta.** Quem aparece pela
   primeira vez em cima da linha nunca foi visto de um dos lados. Vale também
   para o fragmento que nasce depois de uma oclusão — ver §2b.
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

---

## 8. Recontar sem GPU: as trilhas

A visão roda uma vez e grava o que enxergou em `dados/trilhas/<camera>.jsonl`
(JSON Lines, um quadro por linha, quadros vazios inclusive). A contagem recorre
esse arquivo quantas vezes for preciso, **sem GPU, sem vídeo e sem o extra
`visao` instalado**.

| | antes | agora |
|---|---|---|
| Testar um parâmetro no MOT17-09 | ~21 s (passada de YOLO) | < 1 s |
| Varredura de 10 combinações | ~3,5 min | ~4 s |
| Precisa de GPU | sim | não |

O replay alimenta a **mesma** `LinhaDeContagem` do agente ao vivo — não há um
segundo contador. `tests/test_trilhas.py` trava essa equivalência, inclusive a
igualdade dos `id_evento`: se o replay gerasse ids diferentes, reprocessar uma
trilha e enviar o resultado duplicaria tudo no banco em vez de ser reconhecido
como repetido.

Sem contagem manual, a métrica que ainda diz algo é **cruzamentos por pessoa**
(eventos ÷ tracks que geraram evento). O ideal é 1,00; acima disso é a mesma
pessoa contada mais de uma vez, e isso é visível sem referência nenhuma.

---

## 9. Re-identificação: o método está pronto; o número, não

A Etapa 2 (`docs/arquitetura.md`, "Etapa 2") reconhece que a pessoa que saiu
às 12h é a que entrou às 9h, pela aparência — roupa e silhueta — e chama isso
de `P7`, um pseudônimo que vale só naquele dia. **Nada aqui foi medido ainda.**
O que existe é a máquina de medir, e ela é a mesma máquina da seção 8.

### Como se mede

1. Uma execução ao vivo grava a trilha com as assinaturas e uma miniatura por
   travessia (`identificar_pessoas.py --gravar-trilhas --guardar-recortes`).
2. `rotular_pessoas.py --gerar` transforma o índice de miniaturas num CSV; quem
   conhece as pessoas preenche `apelido_real` olhando as imagens. Esse CSV é o
   gabarito.
3. `reprocessar_identidade.py --varredura --gabarito` reconta a trilha para
   cada combinação de `limiar_saida × limiar_reentrada × janela_lote_s` — sem
   GPU, em segundos — e imprime, por combinação:

| métrica | pergunta que responde | ideal |
|---|---|---|
| **pureza** | dentro de um `P`, que fração é da mesma pessoa? | 100 % |
| **fragmentação** | uma pessoa real virou quantos `P`? | 1,00 |
| **não atribuído** | que fração das saídas ficou sem par? | baixo, mas **nunca zero à força** |

Pureza e fragmentação puxam para lados opostos: limiar alto dá pureza e
fragmenta; limiar baixo junta e confunde. A combinação escolhida vai declarada
em `config/pipeline.yaml` com esta tabela ao lado — escolher o melhor número de
um dia só e chamar isso de acurácia seria ajuste ao teste, como na seção 2b.

### O que o teste vai decidir

O extrator inicial é o ResNet-18 do torchvision sem a cabeça de classificação:
512 números por recorte, pesos já instalados, zero dependência nova. Foi
treinado para dizer "gato", não "mesma pessoa" — é o ponto de partida mais
barato, não o melhor. `PROJETO.txt` 11.1 já avisou que a ESP32 em VGA
"provavelmente não serve para a fase 2": a pessoa tem 100–200 px de altura e a
rede espera 256; a porta é contraluz.

Três desfechos possíveis, e os três são resultado:

- **(a)** o ResNet-18 separa as ~20 pessoas com pureza alta e fragmentação
  perto de 1 → segue.
- **(b)** não separa → troca-se o extrator por OSNet (`visao/osnet.py`, pesos
  públicos) pela **mesma interface**, recalculando as assinaturas a partir das
  miniaturas já gravadas, e mede-se de novo.
- **(c)** nem o OSNet separa em VGA → o limite é do hardware, e fica registrado
  aqui com o número, como a seção 6 faz com os outros.

### Primeiro sinal (não é medição)

Prova de fumaça em 03/09/2026 sobre `people-detection.mp4` (768×432, 150
quadros): detector + extrator a **36,9 q/s na GPU**, um cruzamento, um `P1`,
uma miniatura e uma linha de assinatura na trilha. Diz que o caminho está
inteiro; não diz nada sobre acurácia.

| | valor |
|---|---|
| pureza | *pendente* |
| fragmentação | *pendente* |
| saídas sem par | *pendente* |
| pessoas únicas / pessoas reais | *pendente* |
| combinação escolhida | *pendente* |
