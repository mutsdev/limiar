# Operação contínua no PC da faculdade

Como deixar o Limiar rodando 24h num Windows sem direitos de administrador, e
o que fazer quando algo cair.

## O desenho

Um único comando sobe tudo:

```
python scripts/rodar_tudo.py entrada_real
```

Ele lança e vigia três filhos — **serviço** (uvicorn, porta 8000), **agente**
(contagem sobre o stream) e **painel** (Streamlit, porta 8501). Filho que
morre é relançado com recuo exponencial (1 s → 60 s), e cinco minutos de vida
estável zeram o recuo. O backup diário do banco também sai daqui.

`--janela` (e `--escala 1.5`) faz o agente mostrar a contagem numa janela, sem
abrir mão de nada do acima: fechar a janela ou apertar `q` reabre em um segundo,
e os totais não zeram — vivem fora do laço. É o modo para quando alguém está
olhando; sem ninguém na frente, rode sem a flag.

As defesas são em camadas, e cada uma cobre a de dentro:

| Camada | Cobre |
|---|---|
| `FonteViva` (dentro do agente) | stream que cai, congela ou nem abre — reconecta com recuo; **10 min sem quadro num endereço http, desiste** e o agente varre a rede atrás da câmera (IP novo por DHCP) |
| laço do `rodar_agente.py` | exceção Python no pipeline — loga e recomeça em 30 s |
| supervisor (`rodar_tudo.py`) | processo que **morre** — relança; processo **travado** — a sonda (`/saude`, pulso do agente, `/_stcore/health`) falha 3× seguidas e ele é derrubado e relançado |
| supervisor (energia) | a máquina não dorme enquanto ele vive (`SetThreadExecutionState`, sem admin) |
| Agendador de Tarefas | logon/reinício da máquina — lança o supervisor, **sem o limite de 72 h** e relançando se cair |
| `Vigia` (observador do supervisor) | o que as camadas acima **não conseguem consertar sozinhas** — manda para o seu celular: filho relançado, sonda sem resposta, câmera parada há 15 min, câmera de volta, e um batimento a cada 6 h |

O que **nenhuma** camada cobre: logoff/reinício sem logon automático, tampa de
notebook fechada, e a câmera em outra rede wifi. Isso é pedido ao TI (abaixo).

**Madrugada:** roda direto. Pausar entre 0h e 6h economizaria nada (uma CPU)
e criaria um ponto de falha às 6h, quando não há ninguém; e a madrugada vazia
é dado — mede falso positivo com a porta parada.

## Checklist do dia no laboratório

Na ordem. Cada passo tem como saber que deu certo.

1. **Código**: `git clone https://github.com/mutsdev/limiar.git` em
   `C:\Users\<usuario>\limiar` (fora de OneDrive). Se já existe: `git pull`.
2. **Dependências**: `uv sync --extra visao` (~2,5 GB; precisa de internet).
   Se a rede do laboratório bloquear o download, o plano B é levar a pasta
   `.venv-limiar` num pendrive e apontar `UV_PROJECT_ENVIRONMENT` para ela.
3. **`.env`** na raiz do clone (copie de `.env.exemplo`):
   `CAMINHO_BANCO=C:/Users/<usuario>/Documents/dados-fluxo/fluxo.db`,
   `SENHA_PAINEL=<uma senha>`, `URL_AVISO=https://ntfy.sh/limiar-<algo difícil>`.
4. **Banco**: copie o `fluxo.db` desta máquina (77 KB, com o período "Teste de
   campo 03/09") para a pasta acima, e rode `uv run scripts/criar_banco.py` —
   cria a tabela `periodo` se faltar e recadastra as câmeras. Idempotente.
5. **Câmera**: ligue na tomada, espere o LED, `uv run scripts/achar_camera.py
   --atualizar entrada_real`. Precisa dizer `CÂMERA: http://<ip>:81/stream`.
6. **Linha**: a porta é outra — **recalibre**:
   `uv run scripts/calibrar_linha.py entrada_real`. Confira em
   `dados/saidas/entrada_real_linha.png` que a linha corta o caminho da porta.
7. **Contagem à mão por 2 min**: `uv run scripts/rodar_agente.py entrada_real
   --janela`. Passe na porta: entrada conta como entrada. `Ctrl+C`.
8. **Túnel**: `uv run scripts/instalar_tunel.py` (baixa o cloudflared, sem admin).
9. **Período**: `uv run scripts/periodo.py --iniciar "Laboratório de física"
   --camera entrada_real`.
10. **Tarefa no logon**: `uv run scripts/instalar_logon.py entrada_real --tunel`.
    Deve imprimir `ÊXITO` e depois o resultado do `powercfg` (se disser que não
    deu, é sem admin — o supervisor segura a máquina acordada mesmo assim).
11. **Subir agora**: `uv run scripts/instalar_logon.py --executar`. Em até 2 min:
    `~/Documents/dados-fluxo/logs/supervisor.log` mostra os quatro filhos
    lançados e `Túnel no ar: https://....trycloudflare.com`.
12. **Do celular, no 4G** (não no wifi do lab): a notificação do ntfy chegou
    (duas, na verdade — a URL do túnel e o batimento *Limiar de pé* com os
    totais, que é a prova de que o canal de aviso funciona);
    abrir a URL pede a senha; a aba **Ao vivo** mostra a porta com a linha; a
    aba **Fluxo** com o período "Laboratório de física" escolhido mostra o que
    você contou no passo 7.
13. **Simule a queda**: feche o agente no Gerenciador de Tarefas. Em 5 s o
    `supervisor.log` mostra `agente morreu` e `lançado (relançamento nº 1)`.
14. **Deslogue e logue de novo**: a tarefa sobe sozinha (a URL do túnel muda,
    e a nova chega no celular).
15. **Peça ao TI**: logon automático da conta (ou ninguém deslogar), suspensão
    de energia desativada, e **reserva de DHCP** para o MAC da câmera.

### Se algo não bater

- **A URL não chegou no celular**: `~/Documents/dados-fluxo/logs/tunel.url`
  tem a última; `tunel.saida.log` diz por que o cloudflared não subiu (sem
  internet de saída na porta 443 é o caso clássico de rede de instituição).
- **Ao vivo diz "sem quadro novo há N s"**: câmera fora do ar ou agente
  parado. `agente_entrada_real.log` mostra qual dos dois; a sonda relança o
  agente sozinha em 3 min se for ele.
- **A câmera mudou de IP** (reinício, queda de luz): depois de 10 min sem
  quadro o agente varre a rede e, achando **uma** câmera, troca e grava no
  `cameras.yaml`. Se houver duas na rede, ele não escolhe — rode o
  `achar_camera.py --atualizar entrada_real` à mão.
- **O painel abriu sem pedir senha**: `SENHA_PAINEL` está vazio no `.env` —
  o `rodar_tudo.py --tunel` se recusa a subir assim; alguém subiu sem `--tunel`
  e expôs de outro jeito. Derrube e corrija.
- **Parou no terceiro dia sem nada no log**: a tarefa foi criada pelo plano B
  (`/sc ONLOGON`), que herda o limite de 72 h. Reinstale; o XML tem de dar
  `ÊXITO`.

## Os avisos no celular

Tudo vai para o mesmo tópico do ntfy (`URL_AVISO`) que já recebia a URL do
túnel. **Com `URL_AVISO` vazio ninguém é avisado de nada** — o `rodar_tudo.py`
reclama no log na subida, mas sobe assim mesmo.

| Chegou | O que aconteceu | O que fazer |
|---|---|---|
| *Limiar de pé* — "N entradas e M saídas hoje" | batimento de 6 h; está tudo funcionando | nada. Confira se o número anda |
| *Limiar reiniciou um processo* | um filho caiu e o supervisor o relançou | um só, nada. Vários seguidos: `supervisor.log` e o `.saida.log` do filho |
| *Limiar sem resposta* | o processo está de pé mas não responde à sonda; o supervisor vai derrubá-lo | espere o relançamento; se repetir, é a máquina no limite |
| *Limiar sem imagem* | 15 min sem quadro nenhum. A recuperação automática já falhou | a câmera caiu de verdade: tomada, cabo, wifi. Ver `achar_camera.py` |
| *Limiar voltou* | quadro chegando de novo | nada. Confira quanto tempo ficou fora |

Cada um sai **uma vez por transição**, não a cada volta do supervisor: câmera
muda avisa ao ficar muda e ao voltar, e não de cinco em cinco segundos.

### O silêncio também é um alarme

Esta é a razão de existir o batimento positivo. Um alerta só chega se houver
alguém vivo para mandá-lo — se o supervisor inteiro morrer, se o Windows
reiniciar, se a máquina perder a rede, **nenhum alerta chega**, e a operação
parada fica indistinguível da operação saudável.

Com uma mensagem a cada 6 h, isso deixa de ser ambíguo: **passou de 6 h sem
batimento, algo está errado.** Em dois dias sem ninguém no laboratório, é o
único sinal que cobre a falha da própria vigilância.

## Acesso de fora: o que sai e o que não sai

Sai **uma porta só**: o painel (8501), por um *quick tunnel* do Cloudflare
(`cloudflared tunnel --url http://127.0.0.1:8501`) — sem conta, sem domínio,
sem admin, conexão só de saída. A URL é aleatória e **muda a cada reinício do
túnel**; por isso o supervisor observa a saída do cloudflared e manda cada URL
nova para `URL_AVISO`, um tópico do ntfy.sh que o celular assina (app ntfy →
"Subscribe to topic" → o mesmo nome do `.env`).

No painel: senha (`SENHA_PAINEL`), a aba **Ao vivo** com o último quadro anotado
(um JPEG por câmera, sobrescrito 5×/s — espelho, não gravação), e em
**Exportar** o CSV dos eventos filtrados e uma cópia consistente do `fluxo.db`.

Não sai: o serviço FastAPI (continua em `127.0.0.1:8000`), o banco em si, o
stream da câmera (que só aceita um cliente, e esse cliente é o agente).

O tópico do ntfy é público para quem souber o nome — escolha um nome difícil, e
a senha do painel é o que protege de verdade.

## Instalar do zero na máquina da faculdade

Windows, sem admin, sem GPU. Tudo é instalado na conta do usuário. Fora de
pasta sincronizada em nuvem (OneDrive) — na máquina da faculdade normalmente
não há, e `C:\Users\<usuario>\limiar` serve.

1. **uv** (gerencia o Python e as dependências; instala sem admin):

   ```
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Feche e reabra o terminal para o `uv` entrar no PATH.

2. **Código**: `git clone https://github.com/mutsdev/limiar.git` — ou, sem
   git, *Code → Download ZIP* no GitHub e descompactar. O que estiver
   commitado é o que chega: **commite e dê push antes** de vir para cá.

3. **Dependências** (o uv baixa o Python 3.11 sozinho; ~2,5 GB por causa do
   PyTorch — as wheels CUDA rodam em CPU sem configurar nada):

   ```
   cd limiar
   uv sync --extra visao
   ```

4. **Câmera**: confira em `config/cameras.yaml` que a `fonte` da
   `entrada_real` é a URL do stream **nesta rede** (o IP do hardware pode ser
   outro na rede da faculdade) e que a linha já está calibrada. A linha é em
   pixels do stream, então a calibração feita em outra máquina vale aqui.

5. **Primeira execução à mão**, da raiz do repositório:

   ```
   uv run scripts/rodar_agente.py entrada_real
   ```

   Precisa de internet uma vez: o `yolo11n.pt` (5,6 MB) é baixado na hora.
   O log em `~/Documents/dados-fluxo/logs/agente_entrada_real.log` deve
   mostrar `Agente iniciando` e, em seguida, eventos ou silêncio sem
   `Sem conexão`. `Ctrl+C` encerra.

6. **Tudo junto**: `uv run scripts/rodar_tudo.py entrada_real` — painel em
   `http://127.0.0.1:8501`, serviço em `http://127.0.0.1:8000/docs`.

7. **Partida no logon**: `uv run scripts/instalar_logon.py entrada_real`.

## Instalar a partida no logon (sem admin)

```
uv run scripts/instalar_logon.py entrada_real --tunel   # cria (ou substitui) a tarefa
uv run scripts/instalar_logon.py --consultar
uv run scripts/instalar_logon.py --executar             # sobe agora, sem relogar
uv run scripts/instalar_logon.py --remover
```

É uma tarefa de logon do próprio usuário — não exige elevação — que lança
`rodar_tudo.py` com o python do ambiente do projeto, caminhos absolutos e
entre aspas (o script monta o comando; digitá-lo à mão é onde o erro entra).

Ela é importada de um **XML** (`fluxo.operacao.agendador.xml_da_tarefa`), e não
criada com `schtasks /sc ONLOGON`, por um motivo: o Windows **encerra tarefas
depois de 72 h** por padrão, e o comando simples não deixa mudar isso. Numa
operação de semanas é a parada silenciosa do terceiro dia. O XML zera o limite
(`ExecutionTimeLimit=PT0S`), relança se o processo cair, ignora bateria e não
deixa subir uma segunda instância. Se o Agendador recusar o XML, o instalador
cai para o comando simples e avisa — funciona, mas com o limite.

Depois, o instalador tenta `powercfg /change standby-timeout-ac 0` (e
hibernate). Sem admin isso pode falhar; não é fatal, porque o supervisor mantém
a máquina acordada por conta própria enquanto vive.

Se a política do laboratório bloquear `schtasks`, o plano B é a pasta
Inicializar: `Win+R` → `shell:startup` → criar `limiar.cmd` com
`"<python do venv>" "<raiz>\scripts\rodar_tudo.py" entrada_real --tunel`.

### O que pedir ao TI da faculdade

- Conta com **logon automático** (ou sessão que ninguém desloga) — a tarefa é
  ONLOGON e o processo morre com o logoff.
- **Suspensão de energia desativada** (o padrão do Windows dorme em 30 min e
  leva o agente junto).
- Se o serviço for exposto na rede: exceção de firewall na porta 8000.
- Upgrade opcional, com admin: instalar como serviço de verdade via NSSM
  (`nssm install Limiar <python> <raiz>\scripts\rodar_tudo.py entrada_real`),
  que roda sem usuário logado. O supervisor continua o mesmo.

## Onde estão os logs

Tudo em `~/Documents/dados-fluxo/logs/` (fora do OneDrive, junto do banco),
com rotação diária e 14 dias de retenção:

- `supervisor.log` — lançamentos, mortes, relançamentos, sondas e a URL do túnel
- `agente_<camera>.log` — reconexões do stream, eventos, batimento horário
- `agente_<camera>.pulso` — arquivo vazio cuja data é o pulso do agente
- `agente_<camera>.quadro` — a data do **último quadro que chegou de verdade**
- `servico.log` — acesso e erros do uvicorn
- `tunel.url` — a URL atual do túnel
- `*.saida.log` — stdout/stderr crus de cada filho; passam de 20 MB e viram `.1`

O batimento no log do agente é a evidência de vida para quem lê: uma linha por
hora com entradas, saídas, tamanho da fila local e reconexões. A evidência que
a máquina lê é o **pulso** — batido a cada 5 s pelo laço que consome a fonte —
e o supervisor derruba e relança o agente com 3 min sem pulso.

### Por que são dois arquivos, e não um

São duas perguntas diferentes, e confundi-las foi o buraco que fechou em
08/09/2026:

| arquivo | responde | quem age |
|---|---|---|
| `.pulso` | "o processo está preso?" | o supervisor, derrubando e relançando |
| `.quadro` | "a câmera está entregando?" | **você**, avisado no celular |

O `.pulso` bate no topo da volta do consumidor, **com quadro ou sem** — a
`FonteViva` acorda no timeout do watchdog e bate do mesmo jeito. Isso é
proposital (câmera fora do ar não é motivo para matar o agente), mas significa
que, sozinho, ele não distingue câmera boa de câmera desligada: processo
saudável, sonda passando, supervisor satisfeito, contagem zero.

O `.quadro` só é tocado depois de um quadro sair da fila de verdade. Ele **não**
alimenta a sonda do supervisor de propósito: relançar o agente não traz a
câmera de volta, e a `FonteViva` já reconecta e varre a rede atrás de um IP
novo sozinha. Ele serve para chamar um humano.

## Expor na rede (quando for preciso)

Por padrão tudo escuta em `127.0.0.1`. Para o serviço aceitar um agente em
outra máquina:

1. Defina `CHAVE_API=<algo-longo-e-aleatorio>` no `.env` **das duas máquinas**.
2. Suba com `--host-servico 0.0.0.0` e aponte `URL_SERVICO` no lado do agente.

Sem chave definida as rotas de escrita ficam abertas — aceitável só em
localhost.

## Backup e restauração

`rodar_tudo.py` faz um backup por dia em `~/Documents/dados-fluxo/backups/`
(`fluxo-AAAA-MM-DD.db`, 14 dias de retenção). À mão:
`python scripts/backup_banco.py`.

Restaurar: parar tudo, copiar o backup sobre `fluxo.db`, subir de novo.

## Testar a resiliência sem o hardware

O ffmpeg desta máquina serve um vídeo local como stream MJPEG:

```
ffmpeg -re -stream_loop -1 -i dados/videos/people-detection.mp4 -c:v mjpeg -q:v 5 -f mpjpeg -content_type "multipart/x-mixed-replace;boundary=ffmpeg" -listen 1 http://127.0.0.1:8090/stream
```

O `-content_type` importa: sem ele o ffmpeg responde `application/octet-stream`,
a `FonteMjpeg` recusa (não é multipart) e a leitura cai para o `VideoCapture`,
que não entrega quadro a tempo — o watchdog derruba, e com `-listen 1` o
ffmpeg morre junto. Com o cabeçalho certo, é o mesmo caminho da câmera real.

Aponte para `http://127.0.0.1:8090/stream` (`rodar_tudo.py entrada_a --tunel
--fonte http://127.0.0.1:8090/stream`, ou `--fonte` no agente), suba e derrube
o ffmpeg no meio: o log deve mostrar a queda, as tentativas com recuo e a
reconexão quando o ffmpeg voltar. Lacuna maior que 30 s deve registrar "estado
de rastreio será zerado". Foi assim que o ensaio de 04/09/2026 conferiu túnel,
aviso no celular, senha, aba Ao vivo e relançamento antes de ir ao laboratório.

Para testar o supervisor: mate um filho no Gerenciador de Tarefas e veja o
relançamento no `supervisor.log`.

O mesmo ensaio prova os avisos, e foi assim que eles foram conferidos em
08/09/2026. Com o agente rodando contra o stream do ffmpeg, compare as datas
dos dois arquivos de pulso enquanto mata o ffmpeg:

```
python -c "import os,time; [print(time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(f)))) for f in ['pulso','quadro']]"
```

Com o stream vivo os dois andam juntos. Matando o ffmpeg, o `.pulso` continua
avançando (o laço gira no timeout do watchdog) e o `.quadro` **congela** — que
é exatamente o estado que nenhuma camada enxergava antes, e que agora vira
*Limiar sem imagem* no celular em 15 min.
