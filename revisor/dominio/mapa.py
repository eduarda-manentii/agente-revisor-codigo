"""Seleção de uma amostra diversa de arquivos de um projeto para gerar o mapa técnico."""
from __future__ import annotations

from typing import Callable

_EXTENSOES_PERMITIDAS = (".java", ".kt", ".ts", ".xml", ".json", ".md", ".gradle", ".sql")
_DIRETORIOS_EXCLUIDOS = frozenset({"node_modules", "target", "dist", "build", ".git", "coverage", "test"})
_SUFIXOS_TESTE = (".spec.ts", "test.java", "tests.java", "it.java")
_SUFIXOS_SEGREDO = (".pem", ".key", ".jks", ".p12")
_NOMES_SEGREDO = ("secret", "credential", "password", "senha")
_PASTAS_COMPARTILHADO = frozenset(
    {"shared", "core", "common", "commons", "util", "utils", "infra", "config", "configuration"}
)


def _partes(caminho: str) -> list[str]:
    return [p for p in caminho.replace("\\", "/").split("/") if p]


def excluido(caminho: str) -> bool:
    """Testes, dependências/gerados e qualquer coisa com cara de segredo nunca entram no mapa."""
    partes = _partes(caminho)
    nome = partes[-1] if partes else caminho
    nome_min = nome.lower()
    diretorios_min = {p.lower() for p in partes[:-1]}
    if diretorios_min & _DIRETORIOS_EXCLUIDOS:
        return True
    if nome_min.endswith(_SUFIXOS_TESTE):
        return True
    if nome_min.startswith("application") and nome_min.endswith((".yml", ".yaml", ".properties")):
        return True
    if nome_min.startswith("bootstrap") or nome_min.startswith(".env"):
        return True
    if any(termo in nome_min for termo in _NOMES_SEGREDO):
        return True
    if nome_min.endswith(_SUFIXOS_SEGREDO):
        return True
    return False


def extensao_permitida(caminho: str) -> bool:
    return caminho.lower().endswith(_EXTENSOES_PERMITIDAS)


def _nome(caminho: str) -> str:
    return _partes(caminho)[-1] if _partes(caminho) else caminho


def _e_manifesto(c: str) -> bool:
    nome = _nome(c)
    return nome in ("pom.xml", "package.json", "angular.json", "build.gradle", "build.gradle.kts")


def _e_readme(c: str) -> bool:
    return _nome(c).lower() in ("readme", "readme.md")


def _e_base(c: str) -> bool:
    nome = _nome(c)
    return (nome.startswith("Abstract") or nome.startswith("Base")) and nome.endswith((".java", ".ts"))


def _e_compartilhado(c: str) -> bool:
    return bool({p.lower() for p in _partes(c)[:-1]} & _PASTAS_COMPARTILHADO)


def _e_controller(c: str) -> bool:
    return _nome(c).endswith("Controller.java")


def _e_service(c: str) -> bool:
    nome = _nome(c)
    return nome.endswith("Service.java") or nome.endswith("ServiceImpl.java")


def _e_repository(c: str) -> bool:
    return _nome(c).endswith("Repository.java")


def _e_mensageria(c: str) -> bool:
    return _nome(c).endswith(("Consumer.java", "Listener.java", "Producer.java", "Publisher.java"))


def _e_mapper(c: str) -> bool:
    return _nome(c).endswith("Mapper.java")


def _e_angular_service(c: str) -> bool:
    return _nome(c).endswith(".service.ts")


def _e_angular_module(c: str) -> bool:
    return _nome(c).endswith((".module.ts", ".routes.ts", "app.config.ts"))


def _e_angular_component(c: str) -> bool:
    return _nome(c).endswith(".component.ts")


# Ordem = prioridade. (nome, predicado, teto)
_CATEGORIAS: list[tuple[str, Callable[[str], bool], int]] = [
    ("manifesto", _e_manifesto, 3),
    ("readme", _e_readme, 2),
    ("base", _e_base, 6),
    ("compartilhado", _e_compartilhado, 10),
    ("controller", _e_controller, 3),
    ("service", _e_service, 3),
    ("repository", _e_repository, 2),
    ("mensageria", _e_mensageria, 3),
    ("mapper", _e_mapper, 2),
    ("angular_service", _e_angular_service, 3),
    ("angular_module", _e_angular_module, 3),
    ("angular_component", _e_angular_component, 3),
]


def selecionar_arquivos_mapa(caminhos: list[str], max_arquivos: int = 30) -> list[str]:
    """Amostra diversa: manifesto/base/compartilhado/camadas primeiro, mais rasos e curtos primeiro."""
    candidatos = [c for c in caminhos if extensao_permitida(c) and not excluido(c)]
    selecionados: list[str] = []
    vistos: set[str] = set()
    for _, predicado, teto in _CATEGORIAS:
        if len(selecionados) >= max_arquivos:
            break
        da_categoria = [c for c in candidatos if c not in vistos and predicado(c)]
        da_categoria.sort(key=lambda c: (len(_partes(c)), len(_nome(c))))
        for c in da_categoria[:teto]:
            selecionados.append(c)
            vistos.add(c)
    return selecionados[:max_arquivos]
