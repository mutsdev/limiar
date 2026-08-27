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
# automático: o rastreador olha por onde as pessoas passam e propõe a linha
python scripts/calibrar_linha.py --camera minha_porta --fonte video.mp4 --sugerir

# manual: dois cliques na linha, o terceiro no lado DE DENTRO
python scripts/calibrar_linha.py --camera minha_porta --fonte video.mp4
```

A câmera é criada em `config/cameras.yaml` se ainda não existir — para testar
um vídeo qualquer não é preciso editar YAML à mão. Os dois modos gravam uma
**prévia em imagem** com a linha desenhada, em `dados/saidas/<camera>_linha.png`.
Olhe essa prévia antes de aceitar; é o passo que pega o item 1 abaixo.

O modo automático também **penaliza posições onde muitos tracks nascem ou
morrem no meio do quadro**, porque é ali que costuma haver oclusor. Não
substitui olhar a prévia: ele infere o obstáculo, não o enxerga.

Use `--nota "por que a linha ficou aqui"` para deixar a razão registrada. Ela
vira campo de dado no YAML e sobrevive à próxima recalibração — comentário de
YAML não sobrevive, porque o arquivo é regravado por programa.

Três regras, e a primeira custou uma passagem perdida no primeiro teste deste
projeto:

1. **Nunca atrás de um oclusor.** Aconteceu duas vezes neste projeto, e é o
   erro de calibração mais caro:

   | caso | oclusor | contagem | depois de mover |
   |---|---|---|---|
   | vídeo de sala | pilar em x≈420-440 | 2 de 3 | 3 de 3 (x=330) |
   | vídeo de corredor | pé de mesa em x≈430-500 | 5 de 6 | 6 de 6 (x=490) |

   A pessoa é ocluída exatamente ao atravessar, o track quebra, e o cruzamento
   se perde — o rastreador registra uma trajetória nascendo já do outro lado.
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
