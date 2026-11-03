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

No review, o agente usa o guia geral, o guia do microserviço do MR (quando existir, prevalece sobre o geral), o mapa técnico do projeto, o arquivo completo de cada arquivo alterado (não só o diff) e os comentários guardados mais parecidos com o código do MR. Os apontamentos que você rejeita entram no próximo treino do guia geral como "o que evitar".

Cada apontamento mostra um bloco **"Por quê"**: a justificativa do modelo e as fontes citadas (comentário real, padrão do guia ou regra do perfil), cada uma conferida contra o que de fato existe — uma citação inventada aparece como descartada, nunca como fonte válida.

**Reler histórico** busca de novo tudo desde `TREINO_DESDE`, ignorando onde parou, e relê o código de todos os microserviços independente da validade do mapa. Use depois de aumentar o período (por exemplo, de 12 para 36 meses); nada é duplicado.

## Instalação (uma vez só)

Pré-requisito: **Python 3.11 ou mais novo**. Confira com `python --version` (no Windows pode ser `py --version`).

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
3. Cole o link do MR, escolha **back** ou **front** e clique em **Revisar MR**. A tela acompanha em tempo real a etapa atual (ex. "Revisando X.java (3 de 12)..."), o tempo decorrido total e na etapa, e mantém um histórico das etapas. Se ficar `LIMITE_INATIVIDADE_SEGUNDOS` sem atualização, aparece um aviso de possível travamento com as opções **Cancelar** e **Reiniciar**.
4. Para cada apontamento: abra o bloco **"Por quê"** para ver a justificativa e as fontes, edite o texto se quiser e clique em **Aprovar**, ou escolha o motivo e clique em **Rejeitar**.
5. Clique em **Publicar aprovados no MR**.

### Ajustar os revisores

Cada revisor é um arquivo em `perfis/`:

- `back.toml` / `front.toml`: descrição, extensões de arquivo, máximo de apontamentos, confiança mínima. O perfil `back` vem configurado só para Java/Spring.
- `instrucoes_back.md` / `instrucoes_front.md`: as regras de review. Cole aqui o conteúdo do seu skill `/revisar-entrega`.

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
- Arquivo alterado com mais de 40 mil caracteres vai para o review só com o diff, sem o arquivo completo.
- O bloco "Por quê" mostra a justificativa que o próprio modelo deu, com as fontes conferidas — não é um registro do raciocínio interno dele.
- Seu código é enviado à Anthropic (pelo Claude Code ou pela API). Confirme que isso é permitido pela política da empresa.
- Com `claude-code`, treinos grandes consomem o mesmo limite de uso que você usa no Claude Code no dia a dia. Se o limite acabar no meio, o treino para e continua de onde parou na próxima vez.
- Com `claude-code`, as configurações do seu usuário em `~/.claude` (como o `CLAUDE.md` global) também são carregadas em cada chamada.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes usam GitLab e LLM falsos (`tests/fakes.py`) e um SQLite temporário; não acessam a rede.

## Estrutura

```
revisor/
├── dominio/       regras puras: diff, apontamento (máquina de estados), heurísticas
├── aplicacao/     casos de uso: revisar, triar/publicar, treinar
├── adaptadores/   GitLab, Anthropic, SQLite
├── portas.py      interfaces entre casos de uso e adaptadores
├── prompts.py     textos enviados ao LLM
└── web/           telas (FastAPI + Jinja2)
```

Para trocar de provedor de LLM, crie em `adaptadores/` uma classe com o método
`completar(sistema, usuario) -> str` e use-a em `revisor/__main__.py`.
