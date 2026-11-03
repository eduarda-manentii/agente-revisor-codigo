"""Heurísticas puras: filtro de ruído, seleção de exemplos e parse da saída do LLM."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from revisor.dominio.apontamento import Severidade
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


def selecionar_exemplos(codigo_alvo: str, exemplos: list[Exemplo], k: int) -> list[Exemplo]:
    """Top-k por similaridade de Jaccard entre identificadores; empate favorece os acolhidos."""
    alvo = tokens(codigo_alvo)
    if not alvo or k <= 0:
        return []
    pontuados: list[tuple[tuple[float, bool], Exemplo]] = []
    for ex in exemplos:
        outro = tokens(ex.trecho)
        jaccard = len(alvo & outro) / len(alvo | outro) if (alvo | outro) else 0.0
        if jaccard > 0:
            pontuados.append(((jaccard, ex.resolvido), ex))
    pontuados.sort(key=lambda item: item[0], reverse=True)
    return [ex for _, ex in pontuados[:k]]


@dataclass(frozen=True)
class ApontamentoSugerido:
    arquivo: str
    linha: int
    severidade: Severidade
    confianca: int
    comentario: str


def parse_saida_llm(texto: str) -> tuple[list[ApontamentoSugerido], int]:
    """Extrai o array JSON da resposta. Retorna (válidos, quantidade de itens descartados)."""
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio == -1 or fim < inicio:
        raise ValueError("A resposta do modelo não contém um array JSON.")
    dados = json.loads(texto[inicio: fim + 1])
    if not isinstance(dados, list):
        raise ValueError("A resposta do modelo não é uma lista.")
    validos: list[ApontamentoSugerido] = []
    descartados = 0
    for item in dados:
        try:
            sugerido = ApontamentoSugerido(
                arquivo=str(item["arquivo"]).strip(),
                linha=int(item["linha"]),
                severidade=Severidade(str(item["severidade"]).upper()),
                confianca=max(1, min(10, int(item["confianca"]))),
                comentario=str(item["comentario"]).strip(),
            )
        except (KeyError, TypeError, ValueError):
            descartados += 1
            continue
        if not sugerido.arquivo or not sugerido.comentario:
            descartados += 1
            continue
        validos.append(sugerido)
    return validos, descartados
