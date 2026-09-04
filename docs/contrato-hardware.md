# Contrato com o time de hardware

O que o time de C++ precisa entregar para o Limiar analisar a câmera da
faculdade. Escrito para ser colado no grupo; a justificativa técnica de cada
pedido está no fim.

## Hardware confirmado (01/09/2026)

**Seeed XIAO ESP32S3 Sense** rodando o exemplo `CameraWebServer` do
[repositório do fabricante](https://github.com/limengdu/SeeedStudio-XIAO-ESP32S3-Sense-camera/tree/main/CameraWebServer_for_esp-arduino_3.0.x),
sem modificação. **É exatamente o caso "stream" deste contrato** — o firmware
já serve MJPEG, e do nosso lado não há uma linha de código a escrever: a URL
entra no campo `fonte` da câmera `entrada_real` em `config/cameras.yaml`.

O que o `startCameraServer()` publica (`app_httpd.cpp`):

| URL | O que é | Quem usa |
|---|---|---|
| `http://IP/` | página web com os controles | as pessoas |
| `http://IP:81/stream` | **MJPEG contínuo** (`multipart/x-mixed-replace`) | **o Limiar** |
| `http://IP/capture` | uma foto JPEG | ninguém, aqui |

A página web e o nosso stream são **portas diferentes do mesmo dispositivo**.
Ninguém precisa abrir a página para o Limiar funcionar.

### Duas correções necessárias no firmware

**1. A resolução padrão inviabiliza a contagem.** O exemplo derruba o sensor
para QVGA logo depois de inicializar, para a página web abrir rápido:

```c
  // drop down frame size for higher initial frame rate
  if (config.pixel_format == PIXFORMAT_JPEG) {
    s->set_framesize(s, FRAMESIZE_QVGA);   // 320x240 — pequeno demais
  }
```

320×240 é **menor que a câmera zenital** que já medimos e descartamos por esse
motivo (402×300: "a pessoa não chega aos 100 px de altura e o detector a
perde" — `config/cameras.yaml`). A troca é de uma palavra:

```c
    s->set_framesize(s, FRAMESIZE_VGA);    // 640x480
```

VGA tem 307 mil pixels, praticamente o mesmo orçamento dos 768×432 em que
medimos 10,9 q/s na CPU (`docs/resultados.md` §3) — e quatro vezes a área do
QVGA. Dá para trocar pelo menu da página web, mas **volta ao padrão a cada
reinício**: numa operação 24h, tem de estar no código.

**2. O IP não é fixo pelo código.** O exemplo usa `WiFi.begin(ssid, password)`
sem `WiFi.config()`, ou seja, DHCP puro: o endereço é o que o roteador der, e
pode mudar depois de uma queda de energia — que é exatamente quando ninguém
está olhando. Duas saídas, qualquer uma serve: **reserva de DHCP** pelo MAC no
roteador, ou `WiFi.config(ip, gateway, subnet, dns)` antes do `WiFi.begin`.

### Um detalhe de operação

O `stream_handler` é um laço infinito dentro da única tarefa do servidor HTTP.
Na prática isso significa **um cliente por vez**: com a página web aberta
mostrando o vídeo, o Limiar não recebe quadros (e vice-versa). Feche a aba
antes de rodar o agente — se o log disser "Sem conexão" com a URL certa, esta
é a primeira suspeita.

O que o Serial imprime (`http://<IP>`) é a página, na porta 80. A URL que
interessa ao Limiar é a mesma com **`:81/stream`** no fim.

## O que pedimos

O firmware deve **expor um stream de vídeo** que o nosso lado puxa:

- **Formato**: MJPEG por HTTP (ex.: `http://IP:81/stream`, o padrão do
  ESP32-CAM) **ou** RTSP/H.264 (se for Raspberry Pi ou câmera IP).
- **Resolução**: 768×432, ou a mais próxima que o sensor der — 800×600 e
  640×480 servem.
- **Taxa**: **10 quadros por segundo ou mais, constantes**. Vir mais rápido
  não atrapalha (descartamos o excedente); vir irregular atrapalha.
- **Rede**: IP fixo na rede local (reserva DHCP ou IP estático). A URL entra
  num arquivo de configuração nosso e não pode mudar a cada reinício.
- **Robustez**: watchdog/reinício automático no firmware. Depois de energizar,
  o stream deve estar de pé sozinho em ~30 s, sem ninguém apertar nada.
- **Privacidade**: o dispositivo não grava imagem nenhuma. Do nosso lado
  também não gravamos — o quadro é analisado em memória e descartado.
- **Autenticação**: sem senha no stream, ou usuário/senha fixos combinados.

## Como validamos juntos

1. Abrir a URL no VLC (Mídia → Abrir transmissão de rede). Se aparecer vídeo,
   o lado do hardware está pronto.
2. Do nosso lado:

   ```
   python scripts/processar_video.py entrada_real --fonte http://IP:81/stream --sem-envio
   ```

## Por que assim

- **MJPEG e não PNG**: o sensor (OV2640 e afins) comprime JPEG em hardware;
  PNG teria de ser codificado por software, é 5–10× maior e não melhora em
  nada a detecção.
- **Stream e não fotos avulsas**: o rastreador precisa de continuidade
  temporal para seguir a mesma pessoa entre quadros. Fotos em intervalos
  irregulares quebram o rastro — e a contagem junto.
- **MP4 nem entra**: é contêiner de vídeo pronto; para enviar ao vivo seria
  preciso fechar segmentos, somando latência e complexidade dos dois lados.
- **10 fps a 768×432**: é o regime medido no PC sem GPU (docs/resultados.md).

## Alternativa, só se o stream for inviável no firmware

O nosso serviço pode receber quadros empurrados: `POST /quadros` com um JPEG
por requisição (multipart, campos `imagem` e `camera_id`), a ≥10 por segundo.
Custa mais código e mais rede — avisem que a gente entrega o endpoint e o
exemplo de requisição.
