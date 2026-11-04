"""Heurísticas puras: filtro de ruído e seleção de exemplos para o treino."""
from __future__ import annotations

import re

from revisor.dominio.modelos import Exemplo

_RUIDO = re.compile(
    r"^\s*(lgtm|ok|okay|blz|beleza|show|top|valeu|obrigad[oa]|feito|done|\+1|👍|✅)[\s!.]*$",
    re.IGNORECASE,
)
_TAMANHO_MINIMO = 15


def e_ruido(comentario: str) -> bool:
    texto = comentario.strip()
    return len(texto) < _TAMANHO_MINIMO or bool(_RUIDO.match(texto))


_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PALAVRAS_GENERICAS = frozenset(
    "the and for return public private protected static final void class import new this "
    "const let var function export from true false null none self def async await string int".split()
)


def tokens(texto: str) -> frozenset[str]:
    return frozenset(
        t.lower() for t in _IDENTIFICADOR.findall(texto) if t.lower() not in _PALAVRAS_GENERICAS
    )


def selecionar_exemplos(
    codigo_alvo: str, exemplos: list[Exemplo], k: int, projeto_mr: str | None = None
) -> list[Exemplo]:
    """Top-k por similaridade de Jaccard entre identificadores; empate favorece os acolhidos.

    Exemplos do mesmo projeto do MR ganham +0,1 de bônus (só entre quem já tem Jaccard > 0).
    """
    alvo = tokens(codigo_alvo)
    if not alvo or k <= 0:
        return []
    pontuados: list[tuple[tuple[float, bool], Exemplo]] = []
    for ex in exemplos:
        outro = tokens(ex.trecho)
        jaccard = len(alvo & outro) / len(alvo | outro) if (alvo | outro) else 0.0
        if jaccard > 0:
            bonus = 0.1 if projeto_mr and ex.projeto == projeto_mr else 0.0
            pontuados.append(((jaccard + bonus, ex.resolvido), ex))
    pontuados.sort(key=lambda item: item[0], reverse=True)
    return [ex for _, ex in pontuados[:k]]
