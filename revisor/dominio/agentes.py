"""Achado de um agente especialista e o parser tolerante da saída JSON dele (R3.6). Schema
diferente do apontamento da chamada única: sem motivo/fontes, com `categoria` (nome do agente) e
`evidencia` obrigatória (trecho que o agente leu pra confirmar o achado)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from revisor.dominio.apontamento import Severidade


class EstadoAgente(StrEnum):
    RODANDO = "RODANDO"
    CONCLUIDO = "CONCLUIDO"
    FALHOU = "FALHOU"
    SEM_RESPOSTA = "SEM_RESPOSTA"
    ENCERRADO_POR_TEMPO = "ENCERRADO_POR_TEMPO"


@dataclass(frozen=True)
class Achado:
    arquivo: str
    linha: int
    severidade: Severidade
    confianca: int
    categoria: str
    comentario: str
    evidencia: str


@dataclass(frozen=True)
class ResultadoAgente:
    agente: str
    achados: tuple[Achado, ...] = ()
    descartados: int = 0
    erro: str = ""
    modelo_usado: str = ""
    resposta_bruta: str = ""


def parse_achados(texto: str, categoria: str) -> tuple[list[Achado], int]:
    """Extrai o array JSON da resposta de um agente. Retorna (válidos, descartados)."""
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio == -1 or fim < inicio:
        raise ValueError("A resposta do agente não contém um array JSON.")
    dados = json.loads(texto[inicio: fim + 1])
    if not isinstance(dados, list):
        raise ValueError("A resposta do agente não é uma lista.")

    validos: list[Achado] = []
    descartados = 0
    for item in dados:
        try:
            evidencia = str(item.get("evidencia", "") or "").strip() if isinstance(item, dict) else ""
            achado = Achado(
                arquivo=str(item["arquivo"]).strip(),
                linha=int(item["linha"]),
                severidade=Severidade(str(item["severidade"]).upper()),
                confianca=max(1, min(10, int(item["confianca"]))),
                categoria=categoria,
                comentario=str(item["comentario"]).strip(),
                evidencia=evidencia,
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            descartados += 1
            continue
        if not achado.arquivo or not achado.comentario or not achado.evidencia:
            descartados += 1
            continue
        validos.append(achado)
    return validos, descartados
