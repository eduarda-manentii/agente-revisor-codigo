# Revisor

Agente de code review que aprende com os comentários reais de toda a equipe no GitLab.
Você cola o link de um MR, escolhe o revisor (back ou front), revisa cada apontamento
(aprova, edita ou rejeita) e publica os aprovados como comentários no MR, no seu nome.

## Como funciona o "treino"

Não existe fine-tuning de modelo. O treino é **sempre cumulativo** e tem quatro etapas:

1. **Descobre os projetos.** Lê todos os projetos dos grupos em `GRUPOS_TREINO` (com subgrupos, sem arquivados) e junta com os avulsos de `PROJETOS_TREINO`, sem duplicar.
2. **Coleta os comentários de todo mundo.** Lê os comentários inline de qualquer revisor nos MRs mergeados de cada projeto, a partir de onde parou naquele projeto (um projeto novo tem o histórico inteiro lido). Ignora respostas do próprio autor do MR e quem estiver em `REVISORES_EXCLUIDOS`. Guarda cada comentário com autor, data e o trecho de código a que se refere. Nada é apagado e nada é duplicado.
3. **Incorpora aos guias.** Existe um guia **geral** (o que a equipe cobra em qualquer projeto) e um guia **por microserviço** (só o que é particular daquele projeto — regras de negócio, componentes internos, armadilhas, convenções), que aparece quando o projeto atinge `MIN_COMENTARIOS_GUIA_MICRO` comentários. Cada lote pendente é **fundido** ao guia atual daquela camada: padrões existentes são mantidos e reforçados, padrões novos são adicionados. Cada lote gera uma versão nova, e as versões anteriores ficam disponíveis na tela do guia. Nenhum comentário é descartado; se o treino cair no meio, os lotes já incorporados ficam salvos e o restante entra no próximo treino.
4. **Lê o código.** Para cada microserviço, lê uma amostra do código (sem testes, segredos ou dependências) e gera um mapa técnico — propósito, stack, arquitetura, componentes internos reutilizáveis, convenções e pontos de atenção — usado no review para não apontar mau uso de algo que a equipe já resolve de outro jeito. Só é refeito quando o mapa vence (`MAPA_VALIDADE_DIAS`) e o código mudou; senão não gasta chamada de LLM.

## Como funciona o review

O review não é mais uma chamada única ao modelo: é um pipeline de agentes especialistas mais um
coordenador, todos rodando sobre um checkout local de verdade do MR (não só o diff).

1. **Workspace.** O Revisor clona (em cache, reaproveitado entre reviews do mesmo projeto) e cria um
   checkout local no `head_sha` exato do MR. Isso é o que dá aos agentes acesso ao código ao redor
   do diff, não só às linhas trocadas. **Precisa de `git` instalado** — sem ele, a avaliação não roda
   (veja "Instalação").
2. **Filtro e risco.** Lockfile, código vendorizado/minificado/gerado (menos migrations) são
   ignorados antes de qualquer coisa. O MR recebe um nível de risco — trivial, leve ou completo —
   pelo tamanho do diff e por mexer em algo sensível (autenticação, segredo, migration). Você vê os
   dois antes de confirmar o review, e pode forçar outro nível.
3. **Agentes especialistas.** Rodam em paralelo (`AGENTES_PARALELOS`), cada um só com acesso de
   leitura ao workspace — quais agentes entram depende do nível de risco (configurável em
   `perfis/<nome>.toml`, seção `[agentes]`). O agente **estilo-revisor** é o que carrega o guia e os
   comentários mais parecidos aprendidos no treino.
4. **Coordenador.** Uma última chamada ao modelo que recebe os achados de todos os agentes já
   pré-agrupados (mesmo arquivo, linhas próximas, mesmo problema aparente viram um grupo só),
   deduplica, descarta especulação/preferência estética/falso positivo, decide a severidade final e
   reescreve cada comentário no tom do guia da equipe. A **Prontidão**, a **recomendação** (Aprovar /
   Aprovar com comentários / Ajustes necessários / Mudanças significativas) e o limite de
   apontamentos por perfil são sempre calculados em código a partir das severidades — o modelo nunca
   decide isso sozinho. Se o coordenador falhar, nada do trabalho dos agentes se perde: cada achado
   vira apontamento direto, com um aviso na tela.

Cada apontamento mostra um bloco **"Por quê"**: quais agentes o encontraram. O que o coordenador
descarta não desaparece — fica numa seção recolhível com o motivo, e dá pra **Recuperar** (volta pra
triagem). Os apontamentos que você rejeita entram no próximo treino do guia geral como "o que evitar".

**Reler histórico** busca de novo tudo desde `TREINO_DESDE`, ignorando onde parou, e relê o código de todos os microserviços independente da validade do mapa. Use depois de aumentar o período (por exemplo, de 12 para 36 meses); nada é duplicado.

## Instalação (uma vez só)

Pré-requisitos: **Python 3.11 ou mais novo** (confira com `python --version`, no Windows pode ser
`py --version`), **git** instalado e no PATH, e o **Claude Code** instalado e logado (`claude`) —
os agentes especialistas e o coordenador sempre rodam via `claude -p`, mesmo que `LLM_PROVEDOR` do
treino esteja como `api`. Sem `git`, a avaliação de MR não funciona (os agentes precisam ler o
código de um checkout de verdade); sem `claude`, o app nem sobe.

```bash
cd revisor-ia
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### Configuração

1. Copie `.env.example` para `.env`.
2. **Token do GitLab**: no GitLab, vá em *Preferências → Access tokens*, crie um token com o escopo `api` e cole em `GITLAB_TOKEN`.
   Esse token escreve no seu nome: não compartilhe o `.env`.
3. **Qual Claude usar** (`LLM_PROVEDOR`):
   - `claude-code` (padrão): usa o Claude Code instalado e logado na sua máquina, consumindo os limites da sua assinatura. Não precisa de chave. Antes de usar, rode `claude` uma vez no terminal e faça login.
   - `api`: usa uma chave da API da Anthropic (console.anthropic.com), cobrada por uso. Preencha `ANTHROPIC_API_KEY`.
4. `GRUPOS_TREINO`: grupos do GitLab (formato da URL, ex. `attornatus/microservicos`) cujos projetos são descobertos automaticamente a cada treino, separados por vírgula.
5. `PROJETOS_TREINO`: projetos avulsos fora desses grupos, no formato da URL (`grupo/projeto`), separados por vírgula. Pelo menos um entre `GRUPOS_TREINO` e `PROJETOS_TREINO` é obrigatório.
6. Opcional: `REVISORES_EXCLUIDOS` (usuários/bots a ignorar no treino, sem `@`), `MIN_COMENTARIOS_GUIA_MICRO` (padrão 30), `MAPA_VALIDADE_DIAS` (padrão 30) e `LIMITE_INATIVIDADE_SEGUNDOS` (padrão 60: segundos sem atualização de uma revisão em andamento até avisar que ela pode ter travado).

## Uso

```bash
python -m revisor
```

Abra http://127.0.0.1:8765 no navegador.

1. Clique em **Treinar** no revisor desejado. O primeiro treino lê os últimos 12 meses (ajuste com `TREINO_DESDE`) e pode demorar.
   Clique em "geral vN" para ler o guia geral, ou na aba de um microserviço para ver o guia próprio dele. Avisos do treino (projetos com falha, etc.) aparecem num bloco recolhível.
2. Veja em **/mapas** o que o agente já leu do código de cada microserviço.
3. Cole o link do MR e escolha **back** ou **front**. Antes de começar, a tela mostra quais arquivos
   vão ser revisados, quais foram ignorados (lockfile, código vendorizado/minificado/gerado — exceto
   migrations) e o nível de risco calculado (trivial/leve/completo, por tamanho e sensibilidade do
   diff); você pode trocar o nível antes de clicar em **Iniciar review**. Depois disso, a tela
   acompanha em tempo real a etapa atual (ex. "Revisando X.java (3 de 12)..."), o tempo decorrido
   total e na etapa, e mantém um histórico das etapas. Se ficar `LIMITE_INATIVIDADE_SEGUNDOS` sem
   atualização, aparece um aviso de possível travamento com as opções **Cancelar** e **Reiniciar**.
4. Para cada apontamento: abra o bloco **"Por quê"** para ver quais agentes encontraram aquilo, edite o texto se quiser e clique em **Aprovar**, ou escolha o motivo e clique em **Rejeitar**. O que o coordenador descartou aparece numa seção recolhível, com o motivo e um botão **Recuperar**.
5. Clique em **Publicar aprovados no MR**.

Ao concluir, a tela mostra uma **Prontidão** de 0 a 100 (100 = nada em aberto; calculada pela
severidade dos apontamentos ainda não rejeitados — não é um número que o modelo inventa, então não
balança de review pra review sem o código mudar). Se já existir um review anterior do mesmo MR, ela
também mostra quantos apontamentos foram **resolvidos**, quantos **se repetem** e quantos são
**novos** — o jeito de saber se está convergindo ou se o agente fica achando coisa nova pra sempre.

### Ajustar os revisores

Cada revisor é um arquivo em `perfis/`:

- `back.toml` / `front.toml`: descrição, extensões de arquivo, máximo de apontamentos, e a seção
  `[agentes]` (quais agentes especialistas rodam em cada nível de risco, com `[agentes.modelo]` pra
  sobrescrever o modelo de um agente específico). O perfil `back` vem configurado só para Java/Spring.
- `instrucoes_back.md` / `instrucoes_front.md`: as regras gerais do perfil.

Os agentes especialistas ficam em `perfis/agentes/`: um `.md` por agente (`generalista`, `qualidade`,
`estilo-revisor`, `testes`, `seguranca`, `performance`), cada um com as seções **"O que apontar"** e
**"O que NÃO apontar"**, mais `REGRAS_COMUNS.md` (aplicado a todos). Pra ajustar o que um agente
procura, edite o `.md` dele.

Para criar outro revisor (por exemplo, SQL), copie um par `.toml` + `.md` e mude o nome.

## Comportamentos importantes

- **Linha inexistente é descartada.** Se o modelo citar uma linha que não está no diff, o apontamento não aparece (a tela mostra quantos foram descartados).
- **MR mudou depois do review.** Se entrarem commits novos antes de você publicar, nada é publicado e os aprovados ficam como "MR mudou depois do review". Rode um novo review.
- **Publicar duas vezes não duplica.** Cada apontamento publicado guarda o id da discussion no GitLab.
- **Falha parcial.** Se um comentário falhar, os outros são publicados; o que falhou mostra o erro e pode ser publicado de novo.
- O servidor só aceita conexões da sua própria máquina (`127.0.0.1`).

## Limitações conhecidas

- Comentários só em linhas adicionadas ou de contexto (lado novo do diff), não em linhas removidas.
- Em GitLab anterior à 15.7, o diff vem do endpoint antigo `/changes`, que pode truncar MRs muito grandes.
- O treino lê só MRs mergeados e só comentários inline (não lê comentários gerais do MR).
- Sem `git` ou sem `claude` instalado/logado, a avaliação de MR não roda (não existe mais um modo
  "só diff" de fallback: os agentes precisam do workspace e todos rodam via Claude Code).
- O bloco "Por quê" mostra quais agentes encontraram o apontamento, não um registro do raciocínio
  interno deles nem citação de comentário histórico específico.
- Seu código é enviado à Anthropic pelo Claude Code (agentes, coordenador e, dependendo de
  `LLM_PROVEDOR`, o treino). Confirme que isso é permitido pela política da empresa.
- Treinos e reviews grandes consomem o mesmo limite de uso que você usa no Claude Code no dia a dia.
  Se o limite acabar no meio de um treino, ele para e continua de onde parou na próxima vez.
- As configurações do seu usuário em `~/.claude` (como o `CLAUDE.md` global) não entram nos agentes
  nem no coordenador (rodam com `--restricted`), mas ainda valem para o treino quando `LLM_PROVEDOR`
  é `claude-code`.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes usam GitLab e LLM falsos (`tests/fakes.py`) e um SQLite temporário; não acessam a rede.

## Estrutura

```
revisor/
├── dominio/       regras puras: diff, apontamento, consolidação, coordenador, risco, sanitização...
├── aplicacao/     casos de uso: revisar (orquestra), executar_agentes, triar/publicar, treinar
├── adaptadores/   GitLab, git (workspace), Claude Code (agentes/coordenador/treino), SQLite
├── portas.py      interfaces entre casos de uso e adaptadores
├── prompts.py     textos enviados ao LLM
└── web/           telas (FastAPI + Jinja2)
```

O treino continua usando `PortaLLM` (`completar(sistema, usuario) -> str`) — pra trocar de provedor
ali, crie um adaptador com esse método e use-o em `revisor/__main__.py`. Agentes e coordenador usam
`PortaAgente`/`PortaCoordenador` (streaming, com acesso de leitura ao workspace) e são fixos no
Claude Code local (`claude -p`), por decisão de arquitetura do pipeline de agentes.
