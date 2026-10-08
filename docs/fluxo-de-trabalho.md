# Fluxo de trabalho

Este documento explica como a equipe pega, faz e entrega tarefas sem depender
de uma pessoa só.

## Equipe

| Quem | Decide | Faz |
|---|---|---|
| João | escopo, prioridade, desempate de merge, contato com o campus | código (agente, painel, calibração), triagem semanal |
| Daniel | rede e máquina do campus: NVR, instalação, operação, cotação | infra, código, revisão de PR |
| Gustavo | — | qualquer tarefa; começa em par com o João na tarefa 10 |
| Renato (orientador) | método de validação, LGPD, enquadramento acadêmico | revisa protocolo e documentos |

Pessoas de fora, como o Estaciona AI, só leem o que é público. Não têm tarefa
nem permissão de escrita.

## Quadro

Usamos o GitHub Projects "Limiar: Fase 1", com estas colunas:

**Entrada → Pronta p/ pegar → Fazendo → Esperando fora → Revisão → Pronta**

- Cada pessoa tem no máximo 2 tarefas em **Fazendo**.
- Tarefa em **Esperando fora** diz quem foi cobrado e quando.

### Etiquetas

- **tipo:** `descoberta`, `código`, `infra`, `dados`, `campo`, `doc`
- **área:** `agente`, `serviço`, `painel`, `operação`, `institucional`
- **prioridade:** `P1` (bloqueia), `P2` (fase 1), `P3` (depois)
- **dependência:** `depende:Q1` a `depende:Q6`
- **`par`:** a tarefa serve para fazer em dupla e aprender junto

## Ciclo de uma tarefa

1. **Criar:** qualquer pessoa cria pelo modelo "Tarefa", e ela cai em
   **Entrada**. O João faz a triagem uma vez por semana.
2. **Pegar:** você se atribui a tarefa e a move para **Fazendo**.
3. **Código:**
   - Crie uma branch a partir da `main` com o nome `tipo/numero-curto`. Exemplo:
     `codigo/10-sem-dados`.
   - Antes do PR, rode `uv run python -m pytest -q`. Precisa passar inteiro.
   - Abra o PR com `Fecha #N` na descrição.
4. **Revisão:** 1 revisor, em até 3 dias. Passado o prazo, qualquer membro pode
   revisar.
5. **Merge:** só com aprovação. Quem abriu o PR faz o merge, por **squash**.
   A `main` é protegida: ninguém faz push direto nela.
6. **Tarefa sem código:** escreva o resultado num comentário da tarefa, com data
   e fonte, e mova para **Pronta**. Se a resposta mudar a arquitetura, atualize
   `docs/implantacao.md`.

## Quando uma tarefa está pronta

- **Código:** o critério de aceite foi demonstrado, os testes passam, o PR foi
  revisado e está na `main`.
- **Outras:** o resultado está escrito na tarefa e o que muda está em
  `implantacao.md`.

## Semana

Não temos reunião fixa.

- **Toda sexta**, cada pessoa comenta na tarefa "Semana AAAA-MM-DD": o que fez,
  o que vai fazer e onde travou.
- **No domingo**, o João lê os comentários e faz a triagem.

## Primeiros passos para quem chega

```
git clone https://github.com/mutsdev/limiar.git
cd limiar
uv sync                    # núcleo (sem visão computacional)
uv run python -m pytest -q
```

Para rodar a visão (YOLO), use `uv sync --extra visao`. São cerca de 2,5 GB.

Leia, nesta ordem:

1. `README.md`
2. `docs/arquitetura.md`
3. `docs/implantacao.md`

Para entender a geometria da contagem, veja `docs/geometria-limiar/apostila.md`.

## Regras que não se quebram

Estão em `docs/arquitetura.md`. As mais importantes:

- **`dados/` nunca entra no git.** São imagens de pessoas reais.
- **Nenhuma coluna identifica uma pessoa.**
- **Senha, token e chave só vão no `.env`.** Nunca no código, numa issue ou num
  PR.
