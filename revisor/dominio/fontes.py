"""Verificação de fontes citadas pelo LLM num apontamento: nada citado vira fonte sem conferir."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TipoFonte(StrEnum):
    COMENTARIO = "COMENTARIO"
    PADRAO_GUIA = "PADRAO_GUIA"
    REGRA_PERFIL = "REGRA_PERFIL"


def _normalizado(texto: str) -> str:
    return " ".join(texto.lower().split())


@dataclass(frozen=True)
class Fontes:
    comentarios: tuple[int, ...] = ()
    comentarios_nao_confirmados: tuple[int, ...] = ()
    padrao_guia: str = ""
    padrao_confirmado: bool = False
    regra_perfil: str = ""
    regra_confirmada: bool = False
    registrada: bool = True  # False = apontamento gravado antes desta versão (coluna fontes nula)

    @property
    def tipos(self) -> tuple[TipoFonte, ...]:
        tipos = []
        if self.comentarios:
            tipos.append(TipoFonte.COMENTARIO)
        if self.padrao_confirmado:
            tipos.append(TipoFonte.PADRAO_GUIA)
        if self.regra_confirmada:
            tipos.append(TipoFonte.REGRA_PERFIL)
        return tuple(tipos)

    @property
    def sem_precedente(self) -> bool:
        return not self.tipos

    @property
    def tem_citacao_nao_confirmada(self) -> bool:
        return bool(self.comentarios_nao_confirmados) or (
            bool(self.padrao_guia) and not self.padrao_confirmado
        ) or (bool(self.regra_perfil) and not self.regra_confirmada)


def parse_ids(valores: list) -> list[int]:
    """Aceita 123, "123" ou "#123"; descarta o que não for número."""
    ids: list[int] = []
    for v in valores:
        texto = str(v).strip().lstrip("#")
        if texto.lstrip("-").isdigit():
            ids.append(int(texto))
    return ids


def verificar_fontes(
    comentarios_citados: list,
    padrao_guia: str,
    regra_perfil: str,
    note_ids_existentes: set[int],
    textos_guia: list[str],
    instrucoes: str,
) -> Fontes:
    ids = parse_ids(comentarios_citados)
    vistos: set[int] = set()
    confirmados: list[int] = []
    nao_confirmados: list[int] = []
    for i in ids:
        if i in vistos:
            continue
        vistos.add(i)
        (confirmados if i in note_ids_existentes else nao_confirmados).append(i)

    padrao = (padrao_guia or "").strip()
    padrao_confirmado = bool(padrao) and any(
        _normalizado(padrao) in _normalizado(texto) for texto in textos_guia if texto
    )
    regra = (regra_perfil or "").strip()
    regra_confirmada = bool(regra) and _normalizado(regra) in _normalizado(instrucoes or "")

    return Fontes(
        comentarios=tuple(confirmados),
        comentarios_nao_confirmados=tuple(nao_confirmados),
        padrao_guia=padrao,
        padrao_confirmado=padrao_confirmado,
        regra_perfil=regra,
        regra_confirmada=regra_confirmada,
        registrada=True,
    )
