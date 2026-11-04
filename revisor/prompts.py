"""Montagem dos prompts. Funções puras: fáceis de testar e de ajustar."""
from __future__ import annotations

from revisor.dominio.apontamento import Apontamento
from revisor.dominio.consolidacao import GrupoAchados
from revisor.dominio.modelos import GERAL, Exemplo, Guia
from revisor.dominio.sanitizacao import sanitizar

_LIMITE_DESCRICAO_MR = 3000
_LIMITE_TRECHO_EXEMPLO = 1200


def _formatar_exemplo(ex: Exemplo) -> str:
    cabecalho = f"[#{ex.note_id}] autor: {ex.autor or '?'} | projeto: {ex.projeto} | arquivo: {ex.arquivo}"
    trecho = sanitizar(ex.trecho[:_LIMITE_TRECHO_EXEMPLO])
    acolhido = " (acolhido pelo autor)" if ex.resolvido else ""
    return f"{cabecalho}{acolhido}\n```\n{trecho}\n```\nComentário do revisor: {sanitizar(ex.comentario)}"


def sistema_destilacao(escopo: str) -> str:
    if escopo == GERAL:
        foco = (
            "Este é o GUIA GERAL: o que a equipe toda cobra em qualquer projeto, e que tipo de "
            "apontamento cada revisor costuma fazer. Não inclua nada específico de um microserviço só."
        )
    else:
        foco = (
            f"Este é o guia do microserviço '{escopo}': inclua só o que é PARTICULAR deste projeto — "
            "regras de negócio, componentes internos, armadilhas e convenções próprias dele. Não "
            "repita o que já vale para qualquer projeto da equipe."
        )
    return (
        "Você mantém um GUIA DE REVIEW da equipe, para que outro revisor consiga revisar código "
        "exatamente como ela revisaria. Você recebe o GUIA ATUAL (pode estar vazio) e um lote de "
        "COMENTÁRIOS NOVOS, e devolve o GUIA COMPLETO ATUALIZADO.\n\n"
        f"{foco}\n\n"
        "O guia é cumulativo. Regras obrigatórias:\n"
        "- NUNCA remova um padrão do guia atual. Só altere um padrão se os comentários novos o "
        "contradisserem explicitamente; nesse caso, registre a mudança no próprio padrão.\n"
        "- Comentário novo que confirma um padrão existente: some à frequência e, se acrescentar algo, "
        "enriqueça o padrão.\n"
        "- Comentário novo que não se encaixa em nenhum padrão: crie um padrão novo.\n"
        "- Padrões equivalentes: funda em um só, somando as frequências.\n"
        "- Não invente padrões que não estejam nos dados.\n\n"
        "Estrutura do guia (Markdown):\n"
        "1. **Tom e estilo de escrita**: tamanho, formalidade, se faz perguntas ou afirmações, se sugere "
        "código, expressões recorrentes.\n"
        "2. **Padrões de apontamento**: um bloco por padrão, começando com uma linha própria "
        "'### <título do padrão>', com: gatilho concreto no código (nome de anotação, padrão de "
        "chamada, tipo de arquivo — nunca tema vago); o que a equipe cobra; severidade típica "
        "(P0/P1/P2); frequência (número de comentários); um exemplo curto parafraseado; e uma linha "
        "'Fontes: #id, #id' com até 5 note_ids (os números entre colchetes [#id] nos cabeçalhos dos "
        "comentários) que representam o padrão — mantenha as fontes antigas e acrescente as novas.\n"
        "3. **O que evitar**: tipos de apontamento que o usuário rejeitou (acumule com os que já estão lá).\n\n"
        "Ordene os padrões por frequência. Seja conciso em cada padrão para o guia continuar cabendo "
        "conforme cresce. Responda só com o guia completo, sem comentários antes ou depois."
    )


def dividir_em_lotes(exemplos: list[Exemplo], limite_caracteres: int) -> list[list[Exemplo]]:
    """Divide TODOS os exemplos em lotes por orçamento de caracteres. Nenhum é descartado."""
    lotes: list[list[Exemplo]] = []
    atual: list[Exemplo] = []
    tamanho = 0
    for ex in exemplos:
        custo = len(_formatar_exemplo(ex))
        if atual and tamanho + custo > limite_caracteres:
            lotes.append(atual)
            atual, tamanho = [], 0
        atual.append(ex)
        tamanho += custo
    if atual:
        lotes.append(atual)
    return lotes


def usuario_destilacao(
    guia_atual: str | None, exemplos: list[Exemplo], rejeitados: list[Apontamento]
) -> str:
    partes = ["# GUIA ATUAL", guia_atual.strip() if guia_atual else "(vazio: este é o primeiro lote)"]
    partes.append(f"# COMENTÁRIOS NOVOS ({len(exemplos)})")
    partes += [_formatar_exemplo(ex) for ex in exemplos] or ["(nenhum comentário novo neste lote)"]
    if rejeitados:
        partes.append("# Apontamentos gerados que o usuário REJEITOU (motivo entre colchetes)")
        for ap in rejeitados:
            partes.append(f"- [{ap.motivo_rejeicao}] {ap.arquivo}: {ap.texto_original[:300]}")
    return "\n\n".join(partes)


def sistema_mapa() -> str:
    return (
        "Você gera um MAPA TÉCNICO de um microserviço para ajudar outro revisor a entender o projeto "
        "antes de revisar código dele. Baseie-se SOMENTE no código mostrado a seguir — nunca invente "
        "stack, convenção ou componente que não apareça nos arquivos. Cubra, nesta ordem:\n"
        "1. Propósito do serviço.\n"
        "2. Stack e versões (linguagem, framework, build).\n"
        "3. Arquitetura e camadas.\n"
        "4. Componentes internos reutilizáveis e como usá-los corretamente (a parte mais importante: "
        "um revisor que não conhece isso aponta problema que não existe).\n"
        "5. Convenções do projeto.\n"
        "6. Integrações externas.\n"
        "7. Pontos de atenção.\n\n"
        "Responda em Markdown, só com o mapa, sem comentários antes ou depois."
    )


def contexto_mr_md(titulo: str, descricao: str, arquivos: list[str], nivel_risco: str) -> str:
    """Resumo gravado em .revisor/contexto-mr.md (R1) — ainda não lido por ninguém nesta fase, mas
    é a base que os agentes especialistas (R3) vão usar em vez de repetir o contexto em cada prompt."""
    partes = [
        f"# {sanitizar(titulo)}", sanitizar(descricao or "(sem descrição)"),
        f"Nível de risco: {nivel_risco}",
        "## Arquivos alterados",
    ]
    partes += [f"- {caminho}" for caminho in arquivos] or ["(nenhum)"]
    return "\n\n".join(partes)


def usuario_agente(arquivos: list[str]) -> str:
    """Prompt genérico de um agente especialista (R3): aponta pros arquivos já escritos no
    workspace (.revisor/) em vez de colar o conteúdo — cada agente lê sozinho via Read/Grep/Glob."""
    partes = [
        "Revise o merge request. O contexto completo (título, descrição, nível de risco) está em "
        "`.revisor/contexto-mr.md`. Leia esse arquivo primeiro.",
        "Diffs já filtrados de cada arquivo alterado (um por arquivo, com o número da linha nova à "
        "esquerda):",
    ]
    partes += [f"- .revisor/diff/{caminho}.patch" for caminho in arquivos]
    partes.append(
        "Leia cada patch e o código ao redor no workspace (mesmo diretório) antes de apontar "
        "qualquer problema. Responda só com o array JSON de achados, no formato combinado."
    )
    return "\n\n".join(partes)


def contexto_estilo_revisor(
    guia_geral: Guia | None, exemplos: list[Exemplo], guia_micro: Guia | None = None,
) -> str:
    """Contexto extra só do agente estilo-revisor (R3.4): guias ativos + exemplos mais parecidos."""
    partes = ["# Guia geral de estilo da equipe",
             guia_geral.conteudo.strip() if guia_geral else "(sem guia geral treinado ainda)"]
    if guia_micro:
        partes += ["# Guia deste microserviço (prevalece sobre o geral em caso de conflito)",
                  guia_micro.conteudo.strip()]
    if exemplos:
        partes.append("# Comentários reais da equipe em códigos parecidos")
        partes += [_formatar_exemplo(ex) for ex in exemplos]
    return "\n\n".join(partes)


def sistema_coordenador(perfil: str) -> str:
    """Papel de juiz (R4.2): consolida os achados pré-agrupados dos agentes num conjunto final de
    apontamentos, no tom do guia da equipe."""
    return (
        f"Você é o coordenador do review de um MR revisado como {perfil}. Você recebe grupos de "
        "achados já pré-agrupados (cada um pode ter vindo de um ou mais agentes especialistas) e "
        "decide o resultado final. Para cada grupo, você deve:\n"
        "- Deduplicar: se dois achados do mesmo grupo descrevem o mesmo problema com palavras "
        "diferentes, trate como um só.\n"
        "- Recategorizar quando fizer sentido (ex.: um problema de performance apontado pelo agente "
        "de qualidade continua sendo um problema de performance).\n"
        "- Descartar especulação, preferência estética sem impacto, falso positivo, e qualquer "
        "achado que contradiga o guia da equipe — abra o arquivo no workspace pra conferir sempre "
        "que não tiver certeza antes de descartar ou manter.\n"
        "- Definir a severidade final (P0 quebra funcionamento/corrompe dado/é vulnerabilidade; P1 "
        "é requisito, padrão ou teste importante; P2 é melhoria que não bloqueia).\n"
        "- Reescrever o comentário no tom e estilo do guia da equipe, pronto para postar no MR.\n\n"
        "Você tem acesso de leitura ao workspace (mesmo diretório dos agentes) para conferir o "
        "código quando precisar. Responda SOMENTE com um objeto JSON, sem texto antes ou depois:\n"
        '{"apontamentos": [{"grupo": <número do grupo>, "severidade": "P0"|"P1"|"P2", '
        '"comentario": "<reescrito no tom do guia>"}],\n'
        ' "descartados": [{"grupo": <número do grupo>, "motivo": "<por que foi descartado>"}],\n'
        ' "resumo": "<até 5 linhas resumindo o review>"}\n\n'
        "Todo grupo numerado que você receber precisa aparecer em EXATAMENTE uma das duas listas "
        "(apontamentos ou descartados). Nunca invente severidade sem embasamento nos achados "
        "recebidos ou no código que você mesmo conferir."
    )


def usuario_coordenador(
    grupos: list[GrupoAchados], guia_geral: Guia | None = None, guia_micro: Guia | None = None,
) -> str:
    partes: list[str] = []
    if guia_geral:
        partes += ["# Guia geral da equipe", guia_geral.conteudo.strip()]
    if guia_micro:
        partes += ["# Guia deste microserviço (prevalece sobre o geral em caso de conflito)",
                  guia_micro.conteudo.strip()]
    partes.append("# Achados pré-agrupados")
    for i, grupo in enumerate(grupos, start=1):
        bloco = [f"## Grupo {i} — {grupo.arquivo}:{grupo.linha} — agentes: {', '.join(grupo.origens)}"]
        for achado in grupo.achados:
            bloco.append(
                f"- [{achado.categoria} | {achado.severidade} | confiança {achado.confianca}] "
                f"{sanitizar(achado.comentario)}\n  Evidência: {sanitizar(achado.evidencia)}"
            )
        partes.append("\n".join(bloco))
    return "\n\n".join(partes)


def usuario_mapa(projeto: str, arquivos: list[tuple[str, str]], pastas: list[str]) -> str:
    partes = [f"# Projeto: {projeto}"]
    if pastas:
        partes.append("# Estrutura de pastas\n" + "\n".join(pastas))
    partes.append("# Arquivos lidos")
    for caminho, conteudo in arquivos:
        partes.append(f"### arquivo: {caminho}\n```\n{conteudo}\n```")
    return "\n\n".join(partes)
