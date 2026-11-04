"""Classificação de erros do LLM e cadeia de modelo de reserva (R5). Funções puras sobre texto:
quem chama decide o que fazer a partir do tipo (nova tentativa, abortar, trocar de modelo)."""
from __future__ import annotations

import re
from enum import StrEnum


class TipoErroLLM(StrEnum):
    SOBRECARGA = "SOBRECARGA"
    LIMITE_USO = "LIMITE_USO"
    NAO_AUTENTICADO = "NAO_AUTENTICADO"
    CONTEXTO_EXCEDIDO = "CONTEXTO_EXCEDIDO"
    SAIDA_INVALIDA = "SAIDA_INVALIDA"
    CANCELADO = "CANCELADO"
    DESCONHECIDO = "DESCONHECIDO"


_PADROES: tuple[tuple[TipoErroLLM, re.Pattern], ...] = (
    (TipoErroLLM.SOBRECARGA, re.compile(r"overloaded|\b5\d\d\b|rate.?limit", re.IGNORECASE)),
    (TipoErroLLM.LIMITE_USO, re.compile(r"usage limit|limite.*atingid", re.IGNORECASE)),
    (TipoErroLLM.NAO_AUTENTICADO, re.compile(r"not logged in|unauthenticated|unauthorized", re.IGNORECASE)),
    (TipoErroLLM.CONTEXTO_EXCEDIDO, re.compile(r"prompt too long|context.*exceed", re.IGNORECASE)),
)

_TENTAR_DE_NOVO = frozenset({TipoErroLLM.SOBRECARGA, TipoErroLLM.SAIDA_INVALIDA})


def classificar_erro(mensagem: str) -> TipoErroLLM:
    for tipo, padrao in _PADROES:
        if padrao.search(mensagem or ""):
            return tipo
    return TipoErroLLM.DESCONHECIDO


def deve_tentar_de_novo(tipo: TipoErroLLM) -> bool:
    return tipo in _TENTAR_DE_NOVO


def proximo_modelo(atual: str, falhas_por_sobrecarga: int, cadeia: dict[str, str], limite: int = 2) -> str | None:
    """Depois de `limite` falhas por sobrecarga do mesmo modelo, cai pro próximo da cadeia
    (ex.: opus -> sonnet -> haiku). None se não houver falhas suficientes ou não houver reserva."""
    if falhas_por_sobrecarga < limite:
        return None
    return cadeia.get(atual)
