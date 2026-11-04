"""Sanitização de texto controlado pelo MR (R8): remove marcadores de fronteira do prompt pra
que título, descrição ou comentário não consigam fechar uma seção mais cedo e injetar instrução
depois dela. Pura: só string in, string out."""
from __future__ import annotations

import re

MARCADORES = ("descricao_mr", "comentarios_mr", "arquivos_alterados", "review_anterior", "guia_revisor")

_PADRAO = re.compile(
    r"</?\s*(?:" + "|".join(MARCADORES) + r")\b[^>]*>", re.IGNORECASE,
)


def sanitizar(texto: str) -> str:
    if not texto:
        return texto
    return _PADRAO.sub("", texto)
