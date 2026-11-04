"""Classificação de risco de um MR (R2): decide quantos agentes rodam, sem LLM nenhum."""
from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath

_PADROES_SENSIVEIS = ("auth", "security", "crypto", "permission", "token", "senha",
                      "migration", "migrations", "migrate")


class NivelRisco(StrEnum):
    TRIVIAL = "TRIVIAL"
    LEVE = "LEVE"
    COMPLETO = "COMPLETO"


def arquivo_sensivel(caminho: str, padroes: tuple[str, ...] = _PADROES_SENSIVEIS) -> bool:
    alvo = str(PurePosixPath(caminho)).lower()
    return any(padrao in alvo for padrao in padroes)


def classificar_risco(num_linhas: int, num_arquivos: int, algum_sensivel: bool) -> NivelRisco:
    """Trivial e leve são checados primeiro; completo é o catch-all (cobre >100 linhas, >50
    arquivos e qualquer combinação fora das duas primeiras faixas) — nunca roda de menos."""
    if algum_sensivel:
        return NivelRisco.COMPLETO
    if num_linhas <= 10 and num_arquivos <= 20:
        return NivelRisco.TRIVIAL
    if num_linhas <= 100 and num_arquivos <= 20:
        return NivelRisco.LEVE
    return NivelRisco.COMPLETO
