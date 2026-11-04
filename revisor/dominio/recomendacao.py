"""Recomendação do coordenador (R4.4/R4.5): sempre calculada em código a partir das severidades
finais — o LLM nunca decide isso, só as severidades de cada apontamento."""
from __future__ import annotations

from enum import StrEnum

from revisor.dominio.apontamento import Severidade


class Recomendacao(StrEnum):
    APROVAR = "APROVAR"
    APROVAR_COM_COMENTARIOS = "APROVAR_COM_COMENTARIOS"
    AJUSTES_NECESSARIOS = "AJUSTES_NECESSARIOS"
    MUDANCAS_SIGNIFICATIVAS = "MUDANCAS_SIGNIFICATIVAS"


def calcular_recomendacao(severidades: list[Severidade]) -> Recomendacao:
    if any(s == Severidade.P0 for s in severidades):
        return Recomendacao.MUDANCAS_SIGNIFICATIVAS
    total_p1 = sum(1 for s in severidades if s == Severidade.P1)
    if total_p1 >= 3:
        return Recomendacao.AJUSTES_NECESSARIOS
    if total_p1 >= 1:
        return Recomendacao.APROVAR_COM_COMENTARIOS
    return Recomendacao.APROVAR  # nenhum apontamento, ou só P2
