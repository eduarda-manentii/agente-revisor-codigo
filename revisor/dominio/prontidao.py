"""Duas métricas puras para responder "esse código já está bom?" sem depender de um número
que o LLM inventa a cada rodada (o que balançaria de review pra review sem o código mudar):

- `calcular_prontidao`: 100 menos uma penalidade por severidade dos apontamentos ainda em
  aberto daquela revisão. Determinístico: só muda se os apontamentos mudarem (o modelo gerou
  menos coisa) ou se você rejeitar um falso positivo — nunca sozinho.
- `comparar_com_anterior`: compara os apontamentos desta revisão com os da revisão anterior do
  mesmo MR, pra mostrar o que foi corrigido, o que ainda se repete e o que é realmente novo —
  o sinal de convergência que "está melhorando" ou "fica achando coisa nova pra sempre".
"""
from __future__ import annotations

from dataclasses import dataclass

from revisor.dominio.apontamento import Apontamento, Severidade, Status

_PESO_SEVERIDADE = {Severidade.P0: 25, Severidade.P1: 10, Severidade.P2: 3}

# Rejeitado = não é um problema de verdade; desatualizado = o MR mudou, não vale mais.
_IGNORADOS_NA_PRONTIDAO = frozenset({Status.REJEITADO, Status.DESATUALIZADO})


def calcular_prontidao(apontamentos: list[Apontamento]) -> int:
    """100 = nada em aberto. Cada apontamento pendente/aprovado/publicado pesa pela severidade."""
    penalidade = sum(
        _PESO_SEVERIDADE[a.severidade] for a in apontamentos if a.status not in _IGNORADOS_NA_PRONTIDAO
    )
    return max(0, 100 - penalidade)


def _normalizar(texto: str) -> str:
    return " ".join(texto.lower().split())


def _chave(ap: Apontamento) -> tuple[str, int, str]:
    return (ap.arquivo, ap.linha, _normalizar(ap.texto_original))


@dataclass(frozen=True)
class Comparacao:
    resolvidos: int  # estava na revisão anterior, não aparece mais nesta
    repetidos: int  # o mesmo apontamento (arquivo + linha + texto) apareceu nas duas
    novos: int  # aparece só nesta revisão


def comparar_com_anterior(atuais: list[Apontamento], anteriores: list[Apontamento]) -> Comparacao:
    """Casa por (arquivo, linha, texto original normalizado) — não importa o status da triagem,
    só se o mesmo problema ainda aparece no diff atual."""
    chaves_atuais = {_chave(a) for a in atuais}
    chaves_anteriores = {_chave(a) for a in anteriores}
    return Comparacao(
        resolvidos=len(chaves_anteriores - chaves_atuais),
        repetidos=len(chaves_atuais & chaves_anteriores),
        novos=len(chaves_atuais - chaves_anteriores),
    )
