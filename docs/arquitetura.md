# Arquitetura

## Camadas

A dependência só aponta para baixo. Nunca o contrário.

```
scripts/            entrypoints finos: argumentos e uma chamada
   |
   v
agente/  servico/   orquestração e transporte
operacao/           supervisor, agendador, pulso, túnel, descoberta — sem cv2
   |
   v
visao/              OpenCV e ultralytics vivem SÓ aqui
   |
   v
contagem/           geometria pura: sem numpy, sem cv2
   |
   v
dominio/            evento, rastro e período; sem infraestrutura
```

`operacao/` é a camada de "ficar de pé": lógica pura com relógio, lançador e
sonda injetáveis, para os testes exercitarem morte, travamento, recuo e a URL
do túnel sem subprocesso nem rede. `visao.quadro_vivo` é a única ponte para
fora — o agente publica o último quadro anotado num JPEG e o painel o lê.

**Por que `contagem` não pode importar numpy:** é o componente que decide se
alguém passou — o mais crítico do sistema. Mantê-lo em Python puro permite
provar seu comportamento com dezenas de casos em milissegundos, sem GPU, sem
modelo e sem vídeo. Instalar a camada de visão custa 2,5 GB; o núcleo continua
testável sem ela.

**Por que `Rastro` mora em `dominio` e não em `visao`:** `contagem` precisa
dele e não pode depender de `visao`. Uma pessoa sendo acompanhada é conceito do
problema, não da biblioteca.

## Dois processos

O agente processa o vídeo e produz eventos; o serviço recebe e grava. No local
eles estarão em máquinas diferentes — a câmera na porta, o banco no servidor.
Nascer monolítico significaria reescrever na hora de instalar.

A separação também permitiu construir o painel inteiro com dados sintéticos,
antes de a visão computacional existir.

```
câmera A ─→ agente A ─┐
                      ├─ HTTP POST /eventos/lote ─→ serviço ─→ SQLite ─→ painel
câmera B ─→ agente B ─┘
```

## Idempotência

Cada evento carrega `id_evento`, derivado de forma determinística de
`(câmera, track, direção, segundo)`. A coluna é `UNIQUE`.

Sem isso, uma queda de rede seguida de reenvio infla a contagem — **e o erro é
silencioso**, porque o número continua parecendo plausível. É a razão de o
reenvio ser seguro e, portanto, de a fila local poder existir.

## A fila local

Quando o serviço não responde, o agente grava em JSONL e segue contando. Na
execução seguinte, drena antes de começar.

Os eventos sobem em lote de 25 **ou quando o mais velho da fila completa 3 s**
(`INTERVALO_ENVIO_S`), o que vier primeiro. Só por tamanho, uma tarde de pouco
movimento deixaria até 24 travessias fora do painel — e fora do banco se o
agente morresse, porque o supervisor relança o processo, não a memória.

Eram 30 s até a Uniube Aberta (26/09/2026), quando o painel no projetor
precisou mostrar a travessia na hora. Com o serviço na mesma máquina, enviar
mais vezes não custa nada, e a perda máxima se o agente morrer cai de 30 s
para 3 s de eventos.

JSONL e não JSON único: uma queda no meio da escrita corrompe no máximo a
última linha, e as anteriores continuam legíveis.

## Origem do dado

A coluna `origem` separa `VISAO` de `SINTETICO`. **Toda consulta de resultado
filtra `VISAO` por padrão** — ver dado de simulação exige pedir. É o que
permite desenvolver e demonstrar o painel com dados falsos sem risco de eles
virarem número de relatório.

## Regras que não se quebram

1. **Nenhum caminho relativo, nenhum `os.chdir()`.** Todo caminho sai de
   `config.py`, absoluto. Caminho relativo quebra quando o script é chamado de
   outra pasta, e o bug é difícil de achar.
2. **O banco fica fora de pasta sincronizada em nuvem.** Sincronização
   concorrente corrompe SQLite.
3. **Scripts são finos.** Lógica mora no pacote, para poder ser testada.
4. **`dados/` nunca entra no git.** É imagem de pessoa real.
5. **Nenhuma coluna identifica pessoa.** Não é lacuna a preencher depois; é a
   definição do sistema.

## Repositório em pasta sincronizada

Se o clone ficar dentro de OneDrive, Google Drive ou Dropbox, o cache de
hardlinks do `uv` colide com o filtro de sincronização (`os error 396`) e a
instalação falha de forma intermitente. Duas decisões no `pyproject.toml`
resolvem isso **para todos**, sem custo para quem está fora:

- `package = false` — o projeto não é construído nem instalado; `src` entra no
  `sys.path` (pytest pela chave `pythonpath`, scripts por três linhas no topo).
- `link-mode = "copy"` — o `uv` copia em vez de criar hardlink. Um pouco mais
  lento, e sempre funciona.

Falta só manter o ambiente virtual fora da pasta sincronizada, para os 2,5 GB do
PyTorch não subirem para a nuvem:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/Documents/dados-fluxo/.venv-limiar"
```

Não é preciso exportar isso para *usar* os scripts: `src/fluxo/ambiente.py`
encontra o ambiente do projeto e se reexecuta nele sozinho.

## Uma dependência de plataforma, e por quê

`[tool.uv.sources]` manda `torch` e `torchvision` para o índice CUDA do próprio
PyTorch — mas **só em Windows e Linux**, por marcador de plataforma. O índice
`cu124` não publica wheel para macOS: sem o marcador, `uv sync --extra visao`
não instala mais devagar num Mac, ele **falha na resolução**. Fora dessas duas
plataformas a dependência cai no PyPI, que no Mac é o build correto de qualquer
forma — Apple Silicon usa Metal, não CUDA.

## Como crescer

A etapa 2 (re-identificação) entrou como `reid/`, irmão de `contagem/`,
consumindo `dominio` e consumido por `agente`. Nenhuma camada existente mudou
de lugar — e a contagem de produção não mudou de comportamento.

## Etapa 2: re-identificação anônima

```
scripts/identificar_pessoas.py     script próprio; processar_video.py não muda
   |
   v
agente/identidade.py               orquestra: recorte -> vetor -> galeria -> remetente
agente/processador.py              +1 parâmetro opcional `identidade=None`
   |
   v
visao/aparencia.py                 o ÚNICO módulo do re-ID com torch e cv2
   |
   v
reid/                              puro: assinatura, húngaro, galeria, métricas
   |
   v
dominio/identidade.py              PessoaSessao, Vinculo, Apelido
```

**Por que `reid/` é puro, como `contagem/`:** é o componente que decide "é a
mesma pessoa". A rede transforma imagem em `list[float]` em `visao/aparencia.py`;
tudo daí para baixo recebe vetores prontos, e é provável em milissegundos com
vetores inventados (`tests/test_reid_*.py`). O húngaro é implementação própria
O(n³) porque o conjunto de candidatos é quem está dentro do prédio agora —
dezenas — e uma dependência a mais não se justifica.

**Por que o custo é controlado por construção:** recortar é fatiar um array, e
acontece para todo mundo visível, 1 quadro em N. A rede só roda quando alguém
**cruza** a linha, e só nos recortes daquela pessoa. Zero inferência por quadro.

**Por que a atribuição é em lote, com "não sei" dentro da matriz:** PROJETO
§12(a) e (b). As saídas esperam `janela_lote_s` e são resolvidas juntas pelo
húngaro contra o conjunto de ocupação. A opção "não atribuído" são colunas
fantasmas de custo `1 - limiar` na própria matriz: o algoritmo escolhe "não sei"
sozinho quando nenhum candidato passa do limiar. Não é filtro aplicado depois.

**Por que a trilha ganhou um formato (`trilha/2`):** sem a assinatura gravada
junto do rastro, calibrar o limiar custaria uma passada de vídeo por tentativa —
exatamente o que a trilha foi criada para eliminar. `trilha/1` continua sendo
lida. `scripts/reprocessar_identidade.py --varredura` faz para a identidade o
que `reprocessar.py` faz para a contagem.

### O que é persistido, e por que a regra 5 continua valendo

A regra 5 diz: *nenhuma coluna identifica pessoa*. A etapa 2 grava três tabelas
novas (`persistencia/esquema.sql`), e nenhuma delas a quebra:

| tabela | o que guarda | o que NÃO guarda |
|---|---|---|
| `pessoa_sessao` | `P7`, câmera, dia, primeira/última vez visto, **`dentro`**, **`expira_em`** | vetor, imagem, nome |
| `vinculo` | evento → `P7` (ou → **nenhum**), similaridade, método | nada da pessoa |
| `apelido_teste` | um rótulo dado à mão, **só no teste de validação** | — |

`P7` é um pseudônimo **do dia**: nasce da roupa e morre com ela. Expira **por
construção**, não por política — `repositorio.purgar_expirados` roda a cada
escrita e no arranque do serviço, e apaga o que passou de `expira_em` (48 h,
PROJETO §16.5). Não há caminho de `P7` para matrícula, nome ou rosto.

O **vetor de aparência nunca vai ao banco**. Vive na memória da galeria e, com
`--gravar-trilhas`, na trilha em `dados/` — fora do git, apagável. É
irreversível para imagem.

A **imagem** só toca o disco com `--guardar-recortes`, desligado por padrão, e
só para o teste de validação com pessoas conhecidas: uma miniatura por
travessia em `dados/recortes/<dia>/<câmera>/P7/`, para que alguém consiga dizer
"P7 é a Maria" e medir confusão e fragmentação. Em operação a flag não existe, e
nenhuma imagem é gravada. Apague a pasta quando o gabarito estiver preenchido.

`apelido_teste` é a única tabela que pode ligar um pseudônimo a alguém — e por
isso está **separada**, com esse nome. Em operação fica vazia; o painel nem
mostra a coluna quando ela não tem nada.

`dentro` é o "entrou e ainda não saiu" que sobrevive ao reinício do agente.
Quem o escreve é o **vínculo** (`nova` e `reentrada` ligam, `saida` desliga),
porque é ele que tem fila local e chega mesmo com o serviço fora do ar; o
`PessoaSessao` cobre só o que não gera vínculo — fantasma e virada de dia. No
arranque, `rodar_agente.py --identificar` lê `GET /pessoas` do dia e chama
`Galeria.semear`: a numeração continua de onde parou (P11, não P1 de novo) e
quem estava dentro continua dentro. Essa pessoa semeada **não tem vetor** — ele
nunca vai ao banco —, então não é candidata a nada: a saída dela fica
`nao_atribuido` até `purgar_fantasmas` encerrá-la (12 h). É o preço de não
guardar aparência, e é o preço certo.

`vinculo.id_evento` não é FOREIGN KEY para `evento` de propósito: os eventos
saem do agente em lotes de 25 e o vínculo pode chegar antes. A junção é feita
na consulta. Reenvio de vínculo substitui (chave = `id_evento`); reenvio de
pessoa só alarga as datas (chave = câmera + dia + pseudônimo).

### Regras que a etapa 2 acrescenta

6. **O `id_evento` não muda.** O re-ID nunca reescreve o `id_local` do
   rastreador antes da contagem: a chave de deduplicação continua sendo a mesma
   de antes, e reprocessar uma trilha continua produzindo os mesmos ids.
7. **Com `identidade=None`, o laço do processador é o de antes.** O único ponto
   de contato com a contagem de produção é um parâmetro opcional; `tests/
   test_processador.py` trava que o resultado é igual com e sem ele.
8. **Nunca forçar um par.** Saída sem candidato bom fica `nao_atribuido`, e a
   fração de "não sei" aparece no relatório e no painel. Um par inventado é
   pior que uma lacuna assumida.
9. **Clipe de dúvida é imagem, e segue a regra da imagem.** `--clipes` grava
   ~12 s de vídeo **anotado** em volta de cada momento duvidoso em
   `dados/revisao/<dia>/<câmera>/`, com um JSON dizendo o que o sistema achou
   e com que parâmetros. Mesmo regime do `--guardar-recortes` (PROJETO §16.2):
   desligado por padrão, só em validação, autorização por escrito, disco local,
   nunca no banco nem na API. Apagado em 48 h (`purgar_clipes`, no arranque e a
   cada hora) ou no instante do veredito, o que vier antes. Teto de 200 clipes
   por execução: a ~6 MB cada, sem teto uma câmera ruim enche o disco e ninguém
   julga oito mil vídeos.

### O que dispara um clipe

| gatilho | quem detecta | o que significa |
|---|---|---|
| `contagem` | `LinhaDeContagem.duvidas` | um track morreu a menos de `raio_duvida_px` (padrão 2× a zona morta) da linha **sem cruzar** — o caso "duas pessoas juntas, uma colada na parede" |
| `deteccao` | `clipes.duvidas_de_deteccao` | detecção com confiança abaixo de 0,5 perto da linha: o YOLO quase não viu |
| `reid` | `clipes.duvidas_de_reid` | saída `nao_atribuido`, ou similaridade a ±0,05 de um limiar — o limiar decidiu, não a pessoa |

O veredito (acertou / errou / não sei, mais uma nota) vai para
`dados/revisao/vereditos.csv` e o clipe é apagado na hora. O `errou` por
gatilho é um **limite inferior** das perdas, sem precisar de gabarito completo:
diz quantas das dúvidas eram erro real, e o `motivo` diz qual parâmetro estava
no fio. Se o YOLO nunca viu a pessoa, nenhum gatilho dispara — o clipe só
mostra o que o detector enxergou ao menos uma vez.
