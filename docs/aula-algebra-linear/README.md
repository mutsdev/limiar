# Aula de álgebra linear a partir do Limiar

Material para ensinar **produto vetorial** usando a contagem de pessoas deste
projeto como exemplo. A decisão mais crítica do sistema — "esta pessoa entrou
ou saiu?" — é o sinal de um produto vetorial, e o módulo que a implementa
(`src/fluxo/contagem/geometria.py`, 97 linhas) não importa numpy nem OpenCV.

| arquivo | o que é |
|---|---|
| `slides.html` | 16 slides para projetar (~50 min). Abre com duplo clique |
| `apostila.html` | a matéria desenvolvida, o código explicado, vídeos e exercícios |
| `geometria_aula.py` | as funções da geometria isoladas, com desenho |

Os dois HTML são **offline**: nenhum script externo, nenhuma fonte da web,
nada de CDN. Sala de aula com wifi ruim é a regra.

## Slides

Abra `slides.html` no navegador.

- `←` `→` (ou espaço) navegam, `Home` / `End` vão aos extremos
- `F` entra em tela cheia
- `#7` na URL abre direto num slide, e voltar/avançar do navegador funciona

O **slide 7 é interativo**: arraste o ponto P (e também A e B) e veja o produto
vetorial, o sinal e o sentido do perpendicular (⊙ sai da tela, ⊗ entra)
mudarem ao vivo.

O **slide 15 traz as seis figuras** do `geometria_aula.py`, embutidas no HTML
(continua offline). Teclas `1`–`6` trocam o cenário. Se você mudar o script,
regenere com `--escuro --salvar` e reembuta — o slide não lê arquivo externo.

## O arquivo Python

```bash
python geometria_aula.py                  # todos os cenários
python geometria_aula.py --cenario porta   # um só
python geometria_aula.py --salvar figuras/ # grava PNG em vez de abrir janela
python geometria_aula.py --conferir        # compara com o código de produção
python geometria_aula.py --escuro          # fundo preto, paleta dos slides
```

Cenários: `sinal`, `fora_do_segmento`, `zona_morta`, `borda`, `porta`,
`diagonal`. Cada um prova um ponto da aula.

Precisa de `matplotlib` para desenhar (só para desenhar — as funções
matemáticas são biblioteca padrão). Se o `python` do PATH não tiver, use o
ambiente do projeto: `uv run docs/aula-algebra-linear/geometria_aula.py`.

### `--conferir` é o que mantém o material honesto

Ele roda as funções da aula e as de `fluxo.contagem.geometria` sobre os mesmos
casos — incluindo os de borda de `tests/test_geometria.py` — e exige resultado
idêntico:

```
OK: 36 comparacoes, nenhuma divergencia entre a aula e o projeto.
```

Material didático que diverge do código ensina errado. Se você editar uma
fórmula do `geometria_aula.py` para experimentar em aula, rode isto depois: ele
diz na hora se a aula deixou de bater com o sistema.

**A fonte da verdade é `src/fluxo/contagem/geometria.py`.** O arquivo daqui é
uma cópia didática; nada em `src/` depende dele.
