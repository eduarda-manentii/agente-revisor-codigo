"""Montagem dos prompts. Funções puras: fáceis de testar e de ajustar."""
from __future__ import annotations

from revisor.dominio.apontamento import Apontamento
from revisor.dominio.diff import ArquivoDiff
from revisor.dominio.modelos import Exemplo, Guia, Perfil

_LIMITE_DESCRICAO_MR = 3000
_LIMITE_TRECHO_EXEMPLO = 1200

_FORMATO_SAIDA = """\
Responda SOMENTE com um array JSON, sem texto antes ou depois. Cada item:
{"arquivo": "<caminho exatamente como no cabeçalho '### arquivo:'>",
 "linha": <número da coluna da esquerda do diff>,
 "severidade": "P0" | "P1" | "P2",
 "confianca": <1 a 10>,
 "comentario": "<texto do comentário, pronto para postar no MR>"}

Regras:
- Só comente linhas que têm número à esquerda. Linhas removidas (sem número) não podem ser comentadas.
- P0 = quebra funcionamento, corrompe dado ou é vulnerabilidade. P1 = requisito, padrão ou teste importante.
  P2 = melhoria que não bloqueia.
- Só aponte problemas reais e acionáveis. Nada de elogios, nada de preferência estética sem impacto.
- Confiança abaixo de 5 significa que você não tem certeza: prefira não incluir.
- Escreva o comentário no tom e no estilo descritos no guia do revisor.
- Se não houver nada relevante, responda [].
"""


def sistema_revisao(perfil: Perfil, guia: Guia | None) -> str:
    partes = [
        "Você é um revisor de código experiente fazendo code review de um merge request.",
        "## Instruções do perfil",
        perfil.instrucoes.strip(),
    ]
    if guia:
        partes += [
            "## Guia do revisor (padrões aprendidos com reviews reais — priorize-os)",
            guia.conteudo.strip(),
        ]
    partes += ["## Formato de saída", _FORMATO_SAIDA]
    return "\n\n".join(partes)


def _formatar_exemplo(ex: Exemplo) -> str:
    trecho = ex.trecho[:_LIMITE_TRECHO_EXEMPLO]
    acolhido = " (acolhido pelo autor)" if ex.resolvido else ""
    return f"Arquivo: {ex.arquivo}{acolhido}\n```\n{trecho}\n```\nComentário do revisor: {ex.comentario}"


def usuario_revisao(
    titulo: str, descricao: str, arquivos: list[ArquivoDiff], exemplos: list[Exemplo]
) -> str:
    partes = [f"# MR: {titulo}", (descricao or "(sem descrição)")[:_LIMITE_DESCRICAO_MR]]
    if exemplos:
        partes.append(
            "# Comentários reais do revisor em códigos parecidos (use como referência de estilo e foco)"
        )
        partes += [_formatar_exemplo(ex) for ex in exemplos]
    partes.append("# Diff a revisar")
    partes += [arq.anotado() for arq in arquivos]
    return "\n\n".join(partes)


def sistema_destilacao() -> str:
    return (
        "Você mantém o GUIA DE REVIEW de UMA pessoa, para que outro revisor consiga revisar código "
        "exatamente como ela revisaria. Você recebe o GUIA ATUAL (pode estar vazio) e um lote de "
        "COMENTÁRIOS NOVOS dela, e devolve o GUIA COMPLETO ATUALIZADO.\n\n"
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
        "2. **Padrões de apontamento**: um bloco por padrão, com: título; gatilho concreto no código "
        "(nome de anotação, padrão de chamada, tipo de arquivo — nunca tema vago); o que ela cobra; "
        "severidade típica (P0/P1/P2); frequência (número de comentários); um exemplo curto parafraseado. "
        "Ordene por frequência.\n"
        "3. **O que evitar**: tipos de apontamento que o usuário rejeitou (acumule com os que já estão lá).\n\n"
        "Seja conciso em cada padrão para o guia continuar cabendo conforme cresce. "
        "Responda só com o guia completo, sem comentários antes ou depois."
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
