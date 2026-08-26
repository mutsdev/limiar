# Calibração

Onde a câmera fica e onde a linha é desenhada decidem mais sobre a precisão do
que qualquer limiar do código. Este documento é o manual de quem instalar.

## Onde montar a câmera

| | |
|---|---|
| Altura | 2,5 a 3 m |
| Inclinação | ~20 a 30 graus para baixo |
| Enquadramento | corpo inteiro visível, não só cabeça e ombros |
| Evitar | contraluz direto; porta de vidro com sol atrás |

**Câmera apontada direto para baixo conta bem e inviabiliza a etapa 2.** Sem
ângulo não há aparência visível, e sem aparência não há re-identificação.
Escolher isso agora evita reinstalar depois.

Teste em pelo menos dois horários antes de fixar: uma posição que funciona às
14h pode ficar em contraluz às 17h.

## Onde desenhar a linha

```bash
python scripts/calibrar_linha.py --camera entrada_a --fonte dados/videos/porta.mp4
```

Dois cliques definem a linha. O terceiro clique, do lado de dentro do prédio,
determina o sinal — o script grava tudo em `config/cameras.yaml`.

Três regras, e a primeira custou uma passagem perdida no primeiro teste deste
projeto:

1. **Nunca atrás de um oclusor.** No vídeo de amostra a linha caiu sobre um
   pilar. Uma pessoa foi ocluída exatamente ao atravessar, o track quebrou, e o
   cruzamento se perdeu — o rastreador registrou uma trajetória nascendo já do
   outro lado. Mover a linha 54 px para longe do pilar recuperou a contagem.
   Sintoma no vídeo anotado: tracks que aparecem do nada perto da linha.

2. **Longe da borda do quadro.** Quem entra em cena já do lado de dentro nunca
   foi visto do lado de fora, e o cruzamento não existe para o sistema. Deixe
   espaço para a pessoa ser rastreada por alguns quadros antes de cruzar.

3. **Atravessando o caminho real, não a soleira.** A linha precisa cortar por
   onde os pés passam. Como o ponto de referência é a base da caixa, ela deve
   ficar no plano do chão.

## Ajuste dos limiares

Em `config/pipeline.yaml`. Ajuste por medição, não por raciocínio: rode,
assista ao vídeo anotado, compare com a contagem manual.

| Parâmetro | Aumentar quando | Diminuir quando |
|---|---|---|
| `confianca_minima` | há caixas em objetos parados | pessoas somem em contraluz |
| `zona_morta_px` | a mesma pessoa conta várias vezes | quem passa rente à linha não conta |
| `cooldown_segundos` | há contagem dupla por hesitação | duas pessoas seguidas viram uma |
| `idade_minima_track` | há falso positivo de um quadro só | passagens rápidas se perdem |
| `pular_quadros` | falta desempenho | pessoas "pulam" a linha entre quadros |

Um sinal de que algo está errado sem precisar de contagem manual: **o saldo do
dia**. Entradas e saídas deveriam quase fechar. O painel avisa quando o desvio
passa de 10%.

## O que olhar no vídeo anotado

```bash
python scripts/processar_video.py --camera entrada_a --sem-envio --anotar
```

- **A caixa acompanha a pessoa?** Se treme ou aparece em objeto parado, é
  `confianca_minima`.
- **O número sobre a caixa muda enquanto a pessoa atravessa?** Track quebrado.
  Geralmente é oclusão — mover a linha costuma resolver.
- **O ponto teal está no pé?** É ele que decide o lado, não a caixa.
- **O contador sobe uma vez por pessoa?** Duas vezes é histerese ou cooldown.
