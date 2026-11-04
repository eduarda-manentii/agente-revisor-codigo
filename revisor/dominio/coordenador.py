"""Saída do coordenador (R4.2/R4.3): parser puro, grupo-indexado. O coordenador cita cada grupo
pré-consolidado por número; a "origem" (quais agentes acharam aquilo) vem do nosso código, nunca do
LLM — isso também permite garantir em código que nenhum achado some sem virar apontamento ou
descarte (R4, critério de aceite)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from revisor.dominio.apontamento import Severidade
from revisor.dominio.consolidacao import GrupoAchados

_MOTIVO_NAO_MENCIONADO = "Não mencionado pelo coordenador."
_MOTIVO_LIMITE = "Excedeu o limite de apontamentos do perfil."


@dataclass(frozen=True)
class ApontamentoFinal:
    arquivo: str
    linha: int
    severidade: Severidade
    confianca: int
    comentario: str
    origens: tuple[str, ...]


@dataclass(frozen=True)
class Descarte:
    arquivo: str
    linha: int
    severidade: Severidade
    confianca: int
    comentario: str
    evidencia: str
    motivo: str
    origens: tuple[str, ...]
    recuperado: bool = False
    id: int | None = None


@dataclass(frozen=True)
class ResultadoCoordenacao:
    apontamentos: tuple[ApontamentoFinal, ...] = ()
    descartados: tuple[Descarte, ...] = ()
    resumo: str = ""


def _confianca_do_grupo(grupo: GrupoAchados) -> int:
    return max(a.confianca for a in grupo.achados)


def _grupo_para_descarte(grupo: GrupoAchados, motivo: str) -> Descarte:
    principal = max(grupo.achados, key=lambda a: a.confianca)
    return Descarte(
        arquivo=grupo.arquivo, linha=grupo.linha, severidade=principal.severidade,
        confianca=_confianca_do_grupo(grupo), comentario=principal.comentario,
        evidencia=principal.evidencia, motivo=motivo, origens=grupo.origens,
    )


def interpretar_saida_coordenador(texto: str, grupos: list[GrupoAchados]) -> ResultadoCoordenacao:
    """Extrai o JSON do coordenador (apontamentos/descartados, cada item com `grupo` 1-based) e
    garante que todo grupo apareça em exatamente uma das duas listas."""
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim < inicio:
        raise ValueError("A resposta do coordenador não contém um objeto JSON.")
    dados = json.loads(texto[inicio: fim + 1])

    apontamentos: list[ApontamentoFinal] = []
    descartados: list[Descarte] = []
    vistos: set[int] = set()

    for item in dados.get("apontamentos", []) or []:
        try:
            idx = int(item["grupo"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= idx < len(grupos)) or idx in vistos:
            continue
        vistos.add(idx)
        grupo = grupos[idx]
        try:
            apontamentos.append(ApontamentoFinal(
                arquivo=grupo.arquivo, linha=int(item.get("linha", grupo.linha)),
                severidade=Severidade(str(item["severidade"]).upper()),
                confianca=_confianca_do_grupo(grupo),
                comentario=str(item["comentario"]).strip(), origens=grupo.origens,
            ))
        except (KeyError, TypeError, ValueError):
            vistos.discard(idx)
            continue

    for item in dados.get("descartados", []) or []:
        try:
            idx = int(item["grupo"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= idx < len(grupos)) or idx in vistos:
            continue
        vistos.add(idx)
        descartados.append(_grupo_para_descarte(grupos[idx], str(item.get("motivo", "")).strip()))

    for i, grupo in enumerate(grupos):
        if i not in vistos:
            descartados.append(_grupo_para_descarte(grupo, _MOTIVO_NAO_MENCIONADO))

    resumo = str(dados.get("resumo", "") or "").strip()
    return ResultadoCoordenacao(
        apontamentos=tuple(apontamentos), descartados=tuple(descartados), resumo=resumo,
    )


_ORDEM_SEVERIDADE = {Severidade.P0: 0, Severidade.P1: 1, Severidade.P2: 2}


def aplicar_limite(resultado: ResultadoCoordenacao, max_apontamentos: int) -> ResultadoCoordenacao:
    """O que exceder o limite do perfil também vira descarte (R4.7) — nunca desaparece."""
    ordenados = sorted(
        resultado.apontamentos, key=lambda a: (_ORDEM_SEVERIDADE[a.severidade], -a.confianca)
    )
    mantidos = ordenados[:max_apontamentos]
    excedentes = ordenados[max_apontamentos:]
    novos_descartes = tuple(
        Descarte(
            arquivo=a.arquivo, linha=a.linha, severidade=a.severidade, confianca=a.confianca,
            comentario=a.comentario, evidencia="", motivo=_MOTIVO_LIMITE, origens=a.origens,
        )
        for a in excedentes
    )
    return ResultadoCoordenacao(
        apontamentos=tuple(mantidos), descartados=resultado.descartados + novos_descartes,
        resumo=resultado.resumo,
    )
