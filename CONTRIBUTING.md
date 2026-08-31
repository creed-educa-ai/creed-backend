# Cartilha de contribuição — CREED.ai Educa

Vale para todos os repositórios do projeto: `creed-frontend` e `creed-backend`.

Leia uma vez antes do primeiro PR. As regras marcadas com 🔒 são aplicadas
pelo GitHub — não dá para esquecer delas, o push é recusado.

## Fluxo de branches

```
main  ← produção. Só recebe merge vindo de dev.
 ↑
dev   ← branch padrão. Alvo de todo PR de tarefa.
 ↑
sua branch de tarefa
```

- **`main`** — o que está (ou vai) em produção. 🔒 Não aceita push direto,
  não pode ser apagada.
- **`dev`** — integração. É o **alvo padrão** de todo PR: quando você abre um
  PR, o GitHub já aponta para cá. 🔒 Não aceita push direto, não pode ser
  apagada.
- **branch de tarefa** — uma por tarefa do ClickUp. Sai de `dev` e volta para
  `dev`.

Começando uma tarefa:

```bash
git checkout dev
git pull
git checkout -b feat/1-criar-usuarios
```

## Nome da branch

```
<slug>/<id-clickup>-<contexto-da-tarefa>
```

**Exemplo:** `feat/1-criar-usuarios`

| Parte | O que é | Regra |
| --- | --- | --- |
| `feat` | slug do tipo de trabalho | um da tabela abaixo |
| `1` | ID da tarefa no ClickUp | números e letras minúsculas, com **pelo menos um dígito** |
| `criar-usuarios` | contexto em 2–4 palavras | minúsculas, sem acento, separado por hífen |

### Slugs

| Slug | Quando usar |
| --- | --- |
| `feat` | funcionalidade nova |
| `fix` | correção de bug |
| `refactor` | muda o código sem mudar o comportamento |
| `perf` | melhora desempenho |
| `test` | adiciona ou corrige teste |
| `docs` | documentação |
| `style` | formatação, sem efeito em comportamento |
| `chore` | manutenção, dependências, configuração |
| `ci` | pipeline, automação |
| `build` | build, empacotamento, Docker |
| `hotfix` | correção urgente que sai de `main` |
| `release` | preparação de versão |

Bons e maus exemplos:

```
✅ feat/1-criar-usuarios
✅ fix/86ab12-corrigir-login-expirado
✅ docs/12-documentar-setup-local

❌ feature/criar-usuarios       slug inválido e sem ID
❌ feat/criar-usuarios          falta o ID do ClickUp
❌ feat/1-Criar_Usuários        maiúscula, underscore e acento
❌ minha-branch                 sem slug
```

O padrão é cobrado em dois momentos:

1. **no seu `git push`**, por um hook local que recusa a branch antes de subir.
   É conveniência — `--no-verify` passa por cima;
2. 🔒 **no PR**, pelo check obrigatório `nome-da-branch`. Esse não tem escape:
   sem ele verde, o PR não mergeia.

Se cair em qualquer um dos dois, renomeie e empurre de novo:

```bash
git branch -m feat/1-criar-usuarios
git push -u origin feat/1-criar-usuarios
```

## Commits

```
<tipo>(<escopo opcional>): <resumo no imperativo>

<corpo: por que a mudança existe>
```

O **tipo** usa a mesma tabela de slugs acima.

Regras do resumo:

- verbo no **imperativo**: "adicionar", não "adicionado" nem "adiciona";
- começa em minúscula, sem ponto final;
- até 72 caracteres;
- descreve o efeito, não o arquivo mexido.

O **corpo** é opcional para mudanças óbvias e importante para o resto. Ele
responde **por quê**, não o quê — o diff já mostra o quê. É onde entram a
armadilha que você encontrou, a alternativa que descartou e o motivo.

```
✅ feat: permitir filtrar respondentes por país
✅ fix: impedir duplicidade de e-mail no cadastro
✅ chore(deps): subir vite para 5.4

❌ ajustes                     não diz nada
❌ feat: Adicionado filtro.    particípio, maiúscula, ponto final
❌ fix: RespondentesView.tsx   nome de arquivo não é mensagem
```

Escopo é opcional; quando usar, prefira o nome da feature (`respondentes`,
`auth`) ou `deps`.

## Pull Request

1. **Alvo**: `dev` (já vem selecionado). Só PR de release ou `hotfix` aponta
   para `main`.
2. **Título**: mesmo padrão do commit — `feat: permitir filtrar respondentes`.
3. **Descrição**: o que muda, por quê, e como o revisor verifica.
4. **Vincule a tarefa** do ClickUp.

Para mergear, 🔒 o PR precisa de:

- **1 aprovação** de outra pessoa do time (o GitHub não deixa aprovar o
  próprio PR);
- **CI verde** — o check `qualidade` precisa passar;
- **todas as conversas resolvidas**.

🔒 Aprovação é descartada se novos commits chegarem depois dela: quem aprovou
revisa de novo.

Depois do merge, apague a branch de tarefa. `main` e `dev` 🔒 não podem ser
apagadas.

## Revisando

Revisar é parte do trabalho, não favor. Ao revisar:

- rode a branch se a mudança for visual ou de comportamento;
- comente o que precisa mudar e o que é só sugestão — deixe claro qual é qual;
- aprove quando estiver confortável em assinar embaixo. Aprovação não é
  formalidade: com 1 aprovação obrigatória, você é a única revisão.

## Resumo do que é automático

| Regra | `main` | `dev` | outras | Onde é aplicada |
| --- | --- | --- | --- | --- |
| Push direto bloqueado | 🔒 | 🔒 | — | ruleset |
| Não pode ser apagada | 🔒 | 🔒 | — | ruleset |
| Force push bloqueado | 🔒 | 🔒 | — | ruleset |
| PR com 1 aprovação | 🔒 | 🔒 | — | ruleset |
| Conversas resolvidas | 🔒 | 🔒 | — | ruleset |
| CI `qualidade` verde | 🔒 | 🔒 | — | check obrigatório |
| Nome no padrão | — | — | 🔒 | check obrigatório + hook local |

Todo mundo do time tem `write`, então **1 aprovação é o caminho normal**: peça a
um colega e siga.

Existe uma saída de emergência — o papel **admin** está na *bypass list* do
ruleset e mergeia sem aprovação. Duas ressalvas sobre ela:

- **Ser admin, sozinho, não basta.** Sem o ator de bypass cadastrado no ruleset,
  o GitHub recusa o merge até para o dono do repositório: `gh pr merge --admin`
  devolve `Repository rule violations found`. O bypass funciona porque foi
  adicionado de propósito, não porque o papel de admin passa por cima do ruleset.
- **Não é o caminho padrão.** Ele anula a única revisão que o projeto tem. Serve
  para destravar setup ou incidente — não para pular a fila.
