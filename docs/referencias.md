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
