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


@dataclass(frozen=True)
class ApontamentoSugerido:
    arquivo: str
    linha: int
    severidade: Severidade
    confianca: int
    comentario: str
    motivo: str = ""
    fontes_comentarios: tuple[int, ...] = ()
    fontes_padrao_guia: str = ""
    fontes_regra_perfil: str = ""


def _ids_citados(valores) -> tuple[int, ...]:
    if not isinstance(valores, list):
        return ()
    ids: list[int] = []
    for v in valores:
        texto = str(v).strip().lstrip("#")
        if texto.lstrip("-").isdigit():
            ids.append(int(texto))
    return tuple(ids)


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
            fontes = item.get("fontes") if isinstance(item, dict) else None
            fontes = fontes if isinstance(fontes, dict) else {}
            sugerido = ApontamentoSugerido(
                arquivo=str(item["arquivo"]).strip(),
                linha=int(item["linha"]),
                severidade=Severidade(str(item["severidade"]).upper()),
                confianca=max(1, min(10, int(item["confianca"]))),
                comentario=str(item["comentario"]).strip(),
                motivo=str(item.get("motivo", "") or "").strip(),
                fontes_comentarios=_ids_citados(fontes.get("comentarios")),
                fontes_padrao_guia=str(fontes.get("padrao_guia", "") or "").strip(),
                fontes_regra_perfil=str(fontes.get("regra_perfil", "") or "").strip(),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            descartados += 1
            continue
        if not sugerido.arquivo or not sugerido.comentario:
            descartados += 1
            continue
        validos.append(sugerido)
    return validos, descartados
