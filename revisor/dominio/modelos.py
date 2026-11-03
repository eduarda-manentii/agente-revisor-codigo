"""Entidades de apoio: perfil, revisão, exemplo histórico, guia e treino."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from revisor.dominio.diff import ArquivoDiff


@dataclass(frozen=True)
class Perfil:
    nome: str
    descricao: str
    extensoes: tuple[str, ...]
    instrucoes: str
    max_apontamentos: int = 25
    confianca_minima: int = 5

    def aceita(self, caminho: str) -> bool:
        return caminho.lower().endswith(self.extensoes)


def carregar_perfis(pasta: Path) -> dict[str, Perfil]:
    perfis: dict[str, Perfil] = {}
    for arquivo in sorted(pasta.glob("*.toml")):
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        instrucoes = (pasta / dados["instrucoes_arquivo"]).read_text(encoding="utf-8")
        perfil = Perfil(
            nome=dados["nome"],
            descricao=dados.get("descricao", ""),
            extensoes=tuple(e.lower() for e in dados["extensoes"]),
            instrucoes=instrucoes,
            max_apontamentos=int(dados.get("max_apontamentos", 25)),
            confianca_minima=int(dados.get("confianca_minima", 5)),
        )
        perfis[perfil.nome] = perfil
    if not perfis:
        raise ValueError(f"Nenhum perfil encontrado em {pasta}.")
    return perfis


@dataclass(frozen=True)
class RefMR:
    host: str
    projeto: str
    iid: int


_CAMINHO_MR = re.compile(r"^/(?P<projeto>.+?)/-/merge_requests/(?P<iid>\d+)")


def parse_url_mr(url: str) -> RefMR:
    partes = urlparse(url.strip())
    casamento = _CAMINHO_MR.match(partes.path)
    if not partes.netloc or not casamento:
        raise ValueError(
            "Link de MR inválido. Formato esperado: "
            "https://gitlab.exemplo.com/grupo/projeto/-/merge_requests/123"
        )
    return RefMR(partes.netloc.lower(), casamento.group("projeto"), int(casamento.group("iid")))


class StatusExecucao(StrEnum):
    PENDENTE = "PENDENTE"
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDA = "CONCLUIDA"
    ERRO = "ERRO"
    CANCELADA = "CANCELADA"


@dataclass
class Revisao:
    mr_url: str
    projeto: str
    mr_iid: int
    perfil: str
    status: StatusExecucao = StatusExecucao.PENDENTE
    titulo_mr: str = ""
    base_sha: str = ""
    start_sha: str = ""
    head_sha: str = ""
    guia_versao: int | None = None
    guia_micro_versao: int | None = None
    mapa_em: str = ""
    descartados: int = 0
    nota: str = ""
    erro: str = ""
    etapa: str = ""
    etapa_iniciada_em: str = ""
    atualizado_em: str = ""
    criada_em: str = ""
    id: int | None = None


@dataclass(frozen=True)
class EventoRevisao:
    """Uma entrada no histórico de etapas de uma revisão (RF07)."""
    revisao_id: int
    etapa: str
    criado_em: str
    id: int | None = None


@dataclass(frozen=True)
class ComentarioHistorico:
    projeto: str
    mr_iid: int
    note_id: int
    arquivo: str
    linha: int | None
    comentario: str
    resolvido: bool
    autor: str = ""
    criado_em: str = ""
    trecho: str = ""


@dataclass(frozen=True)
class Exemplo:
    perfil: str
    projeto: str
    mr_iid: int
    note_id: int
    arquivo: str
    linha: int | None
    trecho: str
    comentario: str
    resolvido: bool
    autor: str = ""
    criado_em: str = ""


# Escopo especial do guia que vale para todos os projetos (em oposição ao guia de um micro).
GERAL = "(geral)"


@dataclass(frozen=True)
class Guia:
    perfil: str
    escopo: str
    versao: int
    conteudo: str
    exemplos_usados: int  # total acumulado de comentários incorporados até esta versão, nesta camada
    criado_em: str


@dataclass(frozen=True)
class MapaProjeto:
    projeto: str
    sha: str
    conteudo: str
    arquivos_lidos: tuple[str, ...]
    criado_em: str
    id: int | None = None


@dataclass
class Treino:
    perfil: str
    completo: bool = False  # True = relê todo o histórico desde TREINO_DESDE
    status: StatusExecucao = StatusExecucao.PROCESSANDO
    novos_exemplos: int = 0
    guia_versao: int | None = None
    avisos: str = ""
    progresso: str = ""
    erro: str = ""
    iniciado_em: str = ""
    concluido_em: str = ""
    id: int | None = None


@dataclass(frozen=True)
class DadosMR:
    titulo: str
    descricao: str
    base_sha: str
    start_sha: str
    head_sha: str
    arquivos: tuple[ArquivoDiff, ...] = field(default_factory=tuple)
