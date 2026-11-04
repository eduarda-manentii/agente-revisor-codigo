"""Seleção dos arquivos de ADR (decisões de arquitetura) dentro do repositório configurado em
ADR_PROJETO — mesma ideia de `dominio/mapa.py`, mas pra documentação em vez de código."""
from __future__ import annotations

import re

_PADRAO_NUMERADO = re.compile(r"^\d{3,5}[-_]")


def _nome(caminho: str) -> str:
    partes = [p for p in caminho.replace("\\", "/").split("/") if p]
    return partes[-1] if partes else caminho


def selecionar_arquivos_adr(caminhos: list[str], prefixo: str = "") -> list[str]:
    """Só Markdown. Com `prefixo`, mantém só o que está sob essa pasta. Sem prefixo, autodetecta por
    "adr" no caminho (ignorando caixa) ou nome numerado comum de ADR (ex.: 0007-titulo.md). Nunca
    inventa um palpite pior que nada: sem match, devolve lista vazia."""
    candidatos = [c for c in caminhos if c.lower().endswith(".md")]
    if prefixo:
        prefixo_norm = prefixo.strip("/").lower() + "/"
        return sorted(c for c in candidatos if c.lower().startswith(prefixo_norm))
    return sorted(
        c for c in candidatos
        if "adr" in c.lower() or _PADRAO_NUMERADO.match(_nome(c))
    )
