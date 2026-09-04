# Referências externas

Projetos e recursos de fora que resolvem problemas vizinhos ao do Limiar. Não
são dependências: são coisas para ler antes de reinventar.

---

## fall-detection-vison — detecção de quedas por câmera

<https://github.com/bakhtiyorjondadajonov/fall-detection-vison>

Detecta que uma pessoa caiu e permanece no chão, para casa de repouso e
monitoramento domiciliar, sem exigir dispositivo vestível.

**Por que interessa aqui.** A metade de baixo da pilha é a mesma que a nossa —
Ultralytics, YOLO11, rastreio com identidade persistente por pessoa — e a de
cima mostra um caminho que o Limiar ainda não tomou: em vez de decidir por
geometria quadro a quadro, ele **classifica uma janela de tempo**.

| | Limiar | fall-detection-vison |
|---|---|---|
| Detecção | YOLO11 (caixa) | YOLO11-**Pose** (17 pontos de esqueleto) |
| Rastreio | ByteTrack | **BoT-SORT** |
| Decisão | regra geométrica: o pé cruzou a linha | **LSTM** sobre janela de 30 quadros |
| Estado | evento instantâneo | três estados: NORMAL, FALLING, FALLEN |

### As três coisas que vale levar

**1. O BoT-SORT não é biblioteca separada.** Ele vem dentro do `ultralytics`,
igual ao ByteTrack — trocar é mudar `tracker: "botsort.yaml"` no
`config/pipeline.yaml`. Já está previsto como comparação medida em
`docs/resultados.md`; este projeto é evidência de que alguém o usa em produção
para exatamente o que nos falta, que é **manter o id da pessoa sob oclusão**.

**2. Pose em vez de caixa muda o que dá para perguntar.** O esqueleto dá o
ângulo do tronco, e é por isso que eles distinguem "agachou" de "caiu". Para
contar passagem não precisamos disso — mas para a etapa 2 o esqueleto é um sinal
de identidade que a caixa não tem, e mais barato que aparência.

**3. Janela temporal em vez de instante.** Nossa contagem decide no quadro em
que o ponto do pé troca de lado, com histerese e cooldown para segurar o ruído.
Eles classificam 30 quadros de uma vez. É a abordagem que trataria o caso que
hoje declaramos como limitação: quem hesita na porta.

### O que NÃO levar

- **A acurácia relatada (98,2%) não é comparável a nada nosso.** É acurácia de
  classificação quadro a quadro sobre datasets de queda (UR Fall, Le2i) mais
  dados sintéticos. Nosso número é erro de contagem contra anotação humana.
  Colocar os dois lado a lado no relatório seria erro grosseiro.
- **Um LSTM exige dado rotulado.** Eles treinaram com 17.502 amostras. Não temos
  uma única gravação da porta real ainda, e a régua de contagem manual continua
  sendo o gargalo. Trocar regra por rede aqui seria trocar um método verificável
  por um que ainda não temos como treinar.

### Licença

**Não declarada com clareza** — a documentação fala em "uso educacional e de
pesquisa", sem arquivo de licença que estabeleça isso. Na prática: **ler e
aprender, não copiar código.** Sem licença explícita, o padrão legal é todos os
direitos reservados. Se algum trecho for realmente útil, o certo é abrir issue
pedindo esclarecimento antes de usar.

---

## Risco espacial por profundidade monocular — YOLO + SAM + Depth Anything

Post de Karem Marcomini no LinkedIn, 31/08/2026:
<https://www.linkedin.com/feed/update/urn:li:activity:7499968702189109248/>

Sistema de segurança em tempo real para trânsito urbano (e, por extensão,
máquinas industriais): detecta pedestres e veículos com YOLO, rastreia, estima
**profundidade monocular** (Depth Anything) e usa SAM para segmentar, de modo a
medir a distância física real entre as pessoas e os veículos — em vez de
disparar alerta por sobreposição de caixas 2D, que acontece o tempo todo entre
objetos em planos de profundidade diferentes. Uma regra à parte identifica
"montado" (pessoa sobre moto/bicicleta) por sobreposição espacial de caixas e o
exclui dos alertas de pedestre em risco.

**Proveniência: post de vitrine.** Sem repositório, sem licença, sem número de
avaliação — é arquitetura plausível, não resultado. Ler como ideia; não há
nada para comparar com o nosso erro de contagem. A parte mais valiosa da
página é o primeiro comentário (abaixo).

**Por que interessa aqui.** O problema central dele é o nosso problema da
oclusão visto de outro ângulo: **duas coisas que se sobrepõem na tela sem
estar no mesmo lugar do mundo**. O Limiar responde isso sem rede nenhuma,
com uma premissa que a cena da porta permite: pessoa anda no chão, então o
`ponto_base` (pé) em pixels equivale a uma posição no plano do chão, e a
geometria do cruzamento decide o resto.

| | Limiar | post |
|---|---|---|
| Espaço de decisão | plano do chão implícito (ponto do pé, em pixels) | mapa de profundidade por pixel |
| Proximidade | cruzamento de segmento com histerese | distância "métrica" entre máscaras |
| Falso positivo tratado | oclusor fixo (pilar, mesa) — linha recalibrada para longe | sobreposição 2D em planos distintos |
| Regra barata por cima | idade mínima, zona morta, cooldown | "montado" por sobreposição de caixas |
| Custo por quadro | YOLO11n só (10,9 q/s em CPU) | YOLO + SAM + Depth Anything |

### As três coisas que vale levar

**1. A regra do "montado" é o nosso padrão de projeto, confirmado em outro
domínio.** Associação por lógica espacial barata entre detecções — em vez de
um modelo a mais — é exatamente a família das nossas regras de contagem. Se um
dia o Limiar olhar mais classes que pessoa (bicicleta entrando no bicicletário,
por exemplo), a associação pessoa↔veículo por sobreposição é o jeito de não
contar o ciclista duas vezes nem tratá-lo como dois objetos.

**2. A lição do comentário (Sarvex Jatasra): a ordenação é confiável, os
metros são emprestados.** Modelo de profundidade monocular devolve escala
ajustada ao domínio de treino — câmera na altura da rua, cena de direção.
Em outra geometria (teto de galpão, porta de prédio), a **ordem** de
profundidade se mantém, mas a **métrica absoluta deriva** — e um limiar de
alerta em metros herda essa deriva silenciosamente. Duas consequências para
nós:

- É a mesma classe de lição que a câmera zenital já nos ensinou por medição:
  todo modelo pré-treinado carrega a geometria do treino como prior oculto
  (o COCO quase não tem gente vista de cima, e o detector a perde).
- Se a etapa 2 um dia precisar de **distância real no chão** (zona de
  ocupação, aglomeração na porta), a resposta certa para câmera fixa não é
  rede de profundidade: é **homografia do plano do chão** — quatro pontos
  medidos com trena no piso, uma matriz 3×3, metros de verdade para tudo que
  está no chão. Determinística, sem GPU, calibrada uma vez na instalação,
  verificável com a própria trena.

**3. Profundidade é o sinal certo para a cena frontal — que já resolvemos de
graça.** A geometria da porta da faculdade é a da `entrada_frontal_4k`: a
pessoa anda **no eixo da câmera**, afastando-se dela, quase sem deslocamento
lateral. É o único caso em que um sinal de profundidade acrescentaria algo à
caixa — e é exatamente o caso em que a linha **horizontal na soleira** já
converte o avanço em profundidade num cruzamento em pixels, custo zero.
Profundidade monocular só entraria se a soleira não fosse visível no quadro.

### O que NÃO levar

- **SAM e Depth Anything no laço 24h.** O orçamento medido do PC sem GPU é
  10,9 q/s **com o YOLO11n sozinho** (`docs/resultados.md` §3). Qualquer um
  dos dois estoura o orçamento por conta própria; os dois juntos são outra
  classe de hardware.
- **Limiar de decisão em metros sem escala ancorada.** O furo apontado no
  comentário: metros que vêm do prior do modelo, não da cena. Se algum dia
  houver número em metros no Limiar, ele nasce de homografia calibrada com
  trena — nunca do palpite de um checkpoint.
- **Qualquer comparação de resultado.** O post não publica métrica; não há o
  que pôr ao lado do nosso erro contra anotação humana.

### Nota para a banca

As perguntas da audiência do post — oclusão, ID switch, escala métrica — são
as que o Limiar responde **com número medido**: ByteTrack reassocia com
detecção de baixa confiança, a costura de rastro foi medida e desligada porque
não melhorou, e a linha é recalibrada para longe do oclusor com o custo
documentado (uma travessia perdida). É o contraste útil entre vitrine e
medição para a apresentação final.
