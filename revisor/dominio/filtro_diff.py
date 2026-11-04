"""Filtro de ruído do diff (R2): remove lockfile, minificado, vendorizado e gerado antes de
gastar uma chamada de LLM com arquivo que ninguém escreveu de próprio punho. Função pura — quem
chama já traz o cabeçalho (5 primeiras linhas) de cada arquivo, sem I/O aqui."""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from revisor.dominio.diff import ArquivoDiff

_LOCKFILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "composer.lock",
})
_EXTENSOES_MINIFICADAS = (".min.js", ".min.css", ".bundle.js", ".map")
_PASTAS_VENDORIZADAS = frozenset({"vendor", "node_modules", "dist"})
_MARCADORES_GERADO = ("@generated", "auto-generated", "do not edit")
# Migrations costumam ser marcadas como geradas por ferramentas (Flyway, EF, etc.), mas são código
# de negócio de verdade: nunca remover por causa só desse marcador.
_SEGMENTOS_MIGRATION = frozenset({"migration", "migrations", "migrate"})


def _em_pasta_vendorizada(caminho: str) -> bool:
    partes = {p.lower() for p in PurePosixPath(caminho).parts}
    return bool(partes & _PASTAS_VENDORIZADAS)


def _e_migration(caminho: str) -> bool:
    partes = {p.lower() for p in PurePosixPath(caminho).parts}
    return bool(partes & _SEGMENTOS_MIGRATION)


def _parece_gerado(cabecalho: str) -> bool:
    inicio = "\n".join(cabecalho.splitlines()[:5]).lower()
    return any(marcador in inicio for marcador in _MARCADORES_GERADO)


def e_ruido(
    caminho: str, cabecalho: str = "",
    ignorar_extra: tuple[str, ...] = (), nunca_ignorar: tuple[str, ...] = (),
) -> bool:
    if any(fnmatch.fnmatch(caminho, padrao) for padrao in nunca_ignorar):
        return False
    nome = PurePosixPath(caminho).name
    if nome in _LOCKFILES:
        return True
    if caminho.lower().endswith(_EXTENSOES_MINIFICADAS):
        return True
    if _em_pasta_vendorizada(caminho):
        return True
    if _parece_gerado(cabecalho) and not _e_migration(caminho):
        return True
    if any(fnmatch.fnmatch(caminho, padrao) for padrao in ignorar_extra):
        return True
    return False


def filtrar_arquivos(
    arquivos: list[ArquivoDiff], cabecalhos: dict[str, str] | None = None,
    ignorar_extra: tuple[str, ...] = (), nunca_ignorar: tuple[str, ...] = (),
) -> tuple[list[ArquivoDiff], list[str]]:
    """Devolve (mantidos, ignorados) na ordem original. `cabecalhos` é opcional por caminho novo
    (5 primeiras linhas do arquivo); sem ele, só as regras que não dependem de conteúdo valem."""
    cabecalhos = cabecalhos or {}
    mantidos: list[ArquivoDiff] = []
    ignorados: list[str] = []
    for arquivo in arquivos:
        if e_ruido(arquivo.caminho_novo, cabecalhos.get(arquivo.caminho_novo, ""), ignorar_extra, nunca_ignorar):
            ignorados.append(arquivo.caminho_novo)
        else:
            mantidos.append(arquivo)
    return mantidos, ignorados
