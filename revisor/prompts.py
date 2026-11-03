"""Montagem dos prompts. Funções puras: fáceis de testar e de ajustar."""
from __future__ import annotations

from revisor.dominio.apontamento import Apontamento
from revisor.dominio.diff import ArquivoDiff
from revisor.dominio.modelos import GERAL, Exemplo, Guia, MapaProjeto, Perfil

_LIMITE_DESCRICAO_MR = 3000
_LIMITE_TRECHO_EXEMPLO = 1200

_FORMATO_SAIDA = """\
Responda SOMENTE com um array JSON, sem texto antes ou depois. Cada item:
{"arquivo": "<caminho exatamente como no cabeçalho '### arquivo:'>",
 "linha": <número da coluna da esquerda do diff>,
 "severidade": "P0" | "P1" | "P2",
 "confianca": <1 a 10>,
 "comentario": "<texto do comentário, pronto para postar no MR>",
 "motivo": "<por que é um problema: raciocínio técnico e consequência concreta>",
 "fontes": {"comentarios": [<note_ids citados entre colchetes [#id] nos exemplos, ou vazio>],
            "padrao_guia": "<título EXATO de um padrão do guia que embasou o apontamento, ou vazio>",
            "regra_perfil": "<trecho EXATO copiado das instruções do perfil, ou vazio>"}}

Regras:
- Só comente linhas que têm número à esquerda. Linhas removidas (sem número) não podem ser comentadas.
- P0 = quebra funcionamento, corrompe dado ou é vulnerabilidade. P1 = requisito, padrão ou teste importante.
  P2 = melhoria que não bloqueia.
- Só aponte problemas reais e acionáveis. Nada de elogios, nada de preferência estética sem impacto.
- Confiança abaixo de 5 significa que você não tem certeza: prefira não incluir.
- Escreva o comentário no tom e no estilo descritos no guia do revisor.
- Antes de afirmar que algo "não existe", confira no arquivo completo (quando disponível). Sem o
  arquivo completo, não afirme nada sobre o que está fora do diff.
- Use o mapa técnico do microserviço para entender os componentes internos antes de apontar mau uso
  deles (ex.: não diga que falta liberar um recurso se um componente da equipe já faz isso sozinho).
- Em "fontes", cite só o que de fato embasou o apontamento: ids de comentários reais (os [#id] nos
  exemplos), o título exato de um padrão do guia, ou um trecho exato das instruções do perfil. Se um
  padrão do guia embasou o apontamento, cite também os ids das "Fontes:" daquele padrão em
  "comentarios". Nunca invente um id, título ou trecho. Se nada embasou, deixe as três fontes vazias.
- Se não houver nada relevante, responda [].
"""


def sistema_revisao(
    perfil: Perfil, guia_geral: Guia | None, guia_micro: Guia | None = None, mapa: MapaProjeto | None = None
) -> str:
    partes = [
        "Você é um revisor de código experiente fazendo code review de um merge request.",
        "## Instruções do perfil",
        perfil.instrucoes.strip(),
    ]
    if guia_geral:
        partes += [
            "## Guia geral do revisor (padrões aprendidos com reviews reais de toda a equipe — priorize-os)",
            guia_geral.conteudo.strip(),
        ]
    if guia_micro:
        partes += [
            "## Guia deste microserviço (específico do projeto — prevalece sobre o guia geral em "
            "caso de conflito)",
            guia_micro.conteudo.strip(),
        ]
    if mapa:
        partes += [
            "## Mapa técnico deste microserviço (use para entender componentes internos antes de "
            "apontar mau uso deles)",
            mapa.conteudo.strip(),
        ]
    partes += ["## Formato de saída", _FORMATO_SAIDA]
    return "\n\n".join(partes)


def _formatar_exemplo(ex: Exemplo) -> str:
    cabecalho = f"[#{ex.note_id}] autor: {ex.autor or '?'} | projeto: {ex.projeto} | arquivo: {ex.arquivo}"
    trecho = ex.trecho[:_LIMITE_TRECHO_EXEMPLO]
    acolhido = " (acolhido pelo autor)" if ex.resolvido else ""
    return f"{cabecalho}{acolhido}\n```\n{trecho}\n```\nComentário do revisor: {ex.comentario}"


def usuario_revisao(
    titulo: str,
    descricao: str,
    arquivos: list[ArquivoDiff],
    exemplos: list[Exemplo],
    conteudos_completos: dict[str, str] | None = None,
) -> str:
    conteudos_completos = conteudos_completos or {}
    partes = [f"# MR: {titulo}", (descricao or "(sem descrição)")[:_LIMITE_DESCRICAO_MR]]
    if exemplos:
        partes.append(
            "# Comentários reais da equipe em códigos parecidos (use como referência de estilo e foco)"
        )
        partes += [_formatar_exemplo(ex) for ex in exemplos]
    for arq in arquivos:
        conteudo = conteudos_completos.get(arq.caminho_novo)
        if conteudo:
            partes.append(f"# Arquivo completo (versão do MR): {arq.caminho_novo}\n```\n{conteudo}\n```")
    partes.append("# Diff a revisar")
    partes += [arq.anotado() for arq in arquivos]
    return "\n\n".join(partes)


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


def usuario_mapa(projeto: str, arquivos: list[tuple[str, str]], pastas: list[str]) -> str:
    partes = [f"# Projeto: {projeto}"]
    if pastas:
        partes.append("# Estrutura de pastas\n" + "\n".join(pastas))
    partes.append("# Arquivos lidos")
    for caminho, conteudo in arquivos:
        partes.append(f"### arquivo: {caminho}\n```\n{conteudo}\n```")
    return "\n\n".join(partes)
