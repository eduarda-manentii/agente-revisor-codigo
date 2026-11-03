# Revisor

Agente de code review que aprende com os comentários reais de uma pessoa no GitLab.
Você cola o link de um MR, escolhe o revisor (back ou front), revisa cada apontamento
(aprova, edita ou rejeita) e publica os aprovados como comentários no MR, no seu nome.

## Como funciona o "treino"

Não existe fine-tuning de modelo. O treino é **sempre cumulativo**:

1. Lê os comentários inline da pessoa-alvo nos MRs mergeados de cada projeto, a partir de onde parou naquele projeto. Um projeto novo na configuração tem o histórico inteiro lido.
2. Guarda cada comentário com o trecho de código a que ele se refere. Nada é apagado e nada é duplicado.
3. Incorpora ao guia só os comentários que ainda não estão nele. Cada lote é **fundido** ao guia atual: padrões existentes são mantidos e reforçados, padrões novos são adicionados. Cada lote gera uma versão nova, e as versões anteriores ficam disponíveis na tela do guia.
4. Muitos comentários são divididos em vários lotes; nenhum é descartado. Se o treino cair no meio, os lotes já incorporados ficam salvos e o restante entra no próximo treino.

No review, o agente usa o guia mais recente **e** todos os comentários guardados (os mais parecidos com o código do MR entram como exemplo).
Os apontamentos que você rejeita entram no próximo treino como "o que evitar".

**Reler histórico** busca de novo tudo desde `TREINO_DESDE`, ignorando onde parou. Use depois de aumentar o período (por exemplo, de 12 para 36 meses); nada é duplicado.

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
4. `REVISOR_ALVO`: o usuário do GitLab da pessoa cujo estilo você quer copiar.
5. `PROJETOS_TREINO`: os projetos onde ela revisa, no formato da URL (`grupo/projeto`), separados por vírgula.

## Uso

```bash
python -m revisor
```

Abra http://127.0.0.1:8765 no navegador.

1. Clique em **Treinar** no revisor desejado. O primeiro treino lê os últimos 12 meses (ajuste com `TREINO_DESDE`) e pode demorar.
   Clique em "versão N" para ler o guia gerado e conferir se faz sentido.
2. Cole o link do MR, escolha **back** ou **front** e clique em **Revisar MR**.
3. Para cada apontamento: edite o texto se quiser e clique em **Aprovar**, ou escolha o motivo e clique em **Rejeitar**.
4. Clique em **Publicar aprovados no MR**.

### Ajustar os revisores

Cada revisor é um arquivo em `perfis/`:

- `back.toml` / `front.toml`: extensões de arquivo, máximo de apontamentos, confiança mínima.
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
