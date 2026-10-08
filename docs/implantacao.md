# Implantação: fase 1 no campus Vila Gávea

Este documento descreve como o Limiar entra em produção na Uniube. Ele muda
quando chega uma resposta da TI, da direção ou do orientador. Cada mudança
registra a data e de onde veio a informação.

## Escopo da fase 1

- Campus Vila Gávea, contato Colbert.
- Uma porta: a entrada de pedestres do Bloco A, no térreo.
- Uma câmera: "BL.A-TERREO-Saida-Pedestre 2", no NVR-2. A câmera 1 fica de
  reserva caso a validação reprove a 2.

Fora do escopo: outros blocos, estacionamento, mapa de calor e identidade
(`--identificar`).

## Arquitetura

```
NVR-2 (substream RTSP, câmera 2)
   │  rede do campus
   ▼
1 máquina no campus: agente → serviço → SQLite → painel
   │  só saída, porta 443
   ├─→ túnel Cloudflare → painel com senha (direção e equipe)
   └─→ ntfy → aviso de queda no celular da equipe
```

- **Lemos o RTSP pelo NVR, não a câmera direto.** O código já aceita essa
  fonte (`visao/fonte.py`). Basta trocar a `fonte` em `config/cameras.yaml`,
  e o PC da vigilância não é tocado.
- **Usamos o substream.** A detecção roda em 768×432, então o stream principal
  só gastaria banda.
- **A máquina não tem GPU.** Medimos 10,9 quadros/s, o que dá cerca de 10 quadros
  por pessoa no portão; o mínimo é 3. A tarefa 8 confirma isso no stream real.
- **Tudo roda numa máquina só.** Agente e serviço já são processos separados.
  Para dividir em duas máquinas depois, basta configurar `URL_SERVICO` e
  `CHAVE_API`.
- **Nenhuma imagem sai do campus.** Isso vem das regras 4 e 5 de
  `arquitetura.md` e é a base do documento de LGPD.

## Onde a máquina roda

| Ordem | Opção | Custo | Risco |
|---|---|---|---|
| 1 | VM ou servidor da Uniube | R$ 0 | baixo: a TI mantém |
| 2 | Mini PC nosso na rede das câmeras | R$ 2.500–4.000 | baixo: o Daniel administra |
| 3 | PC da vigilância (iVMS-4200) | R$ 0 | alto: alguém pode deslogar ou reiniciar, e a CPU é disputada |
| 4 | Máquina do Estaciona AI | a dividir | indefinido: depende de acordo por escrito |

Requisitos mínimos: 4 núcleos, 8 GB de RAM, 50 GB de disco, Windows ou Linux,
e saída pela porta 443.

## Orçamento

| Item | Com VM | Com mini PC | Observação |
|---|---|---|---|
| Máquina | R$ 0 | R$ 2.500–4.000 | i5/Ryzen 5, 16 GB, SSD 512 GB, cotar 3 lojas |
| GPU | R$ 0 | R$ 0 | só entra se a tarefa 8 medir menos de 8 quadros/s |
| Túnel e avisos | R$ 0 | R$ 0 | Cloudflare e ntfy gratuitos |
| Domínio fixo (opcional) | ~R$ 40/ano | ~R$ 40/ano | link estável para a direção |
| 2 contadores de mão | R$ 40 | R$ 40 | validação |
| Horas | ~71 h | ~74 h | em reais só se a Q6 decidir que é prestação de serviço |

## Perguntas em aberto

| Q | Pergunta | Para | O que muda |
|---|---|---|---|
| Q1 | O NVR libera RTSP? Quem administra? | TI | Não: lemos a câmera direto. Terceirizada: prazo maior |
| Q2 | Podemos pôr uma máquina nossa na rede das câmeras? | TI | Não: VM (Q4) ou PC da vigilância |
| Q3 | O painel pode ser aberto de fora do campus? | Colbert | Não: túnel desligado, painel só na rede interna |
| Q4 | Existe VM ou servidor disponível? | TI | Sim: hardware custa R$ 0 |
| Q5 | Quem responde pela LGPD e que documento ela exige? | Colbert | Define a tarefa 12 |
| Q6 | O projeto é acadêmico, serviço ou os dois? | Renato | Valor-hora, quem assina, licença MIT |

Registro das respostas, com data e fonte:

- Nenhuma ainda.

## Integração com outros projetos

O Estaciona AI propôs um pacote único para a Uniube. Até haver acordo por
escrito sobre código, receita e suporte, vale o seguinte:

- o Limiar continua em repositório próprio;
- a integração acontece só pela API de eventos (`POST /eventos/lote`);
- dividir a máquina exige números: a carga do Estaciona AI mais a nossa.

## Para a fase 2 continuar possível

- Uma câmera por agente, sem nada fixo no código.
- O mapa de calor usaria as posições das trilhas, sem imagem. Se dá para guardar
  essas posições depende da Q5.
