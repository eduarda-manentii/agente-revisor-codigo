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
    ignorar_arquivos: tuple[str, ...] = ()  # padrões extras de ruído (glob), além dos embutidos (R2)
    nunca_ignorar: tuple[str, ...] = ()  # padrões (glob) que nunca contam como ruído, mesmo embutidos
    agentes_por_risco: dict[str, tuple[str, ...]] = field(default_factory=dict)  # R3: por NivelRisco
    modelo_por_agente: dict[str, str] = field(default_factory=dict)

    def aceita(self, caminho: str) -> bool:
        return caminho.lower().endswith(self.extensoes)

    def agentes_do_nivel(self, nivel: str) -> tuple[str, ...]:
        return self.agentes_por_risco.get(nivel, ())


def carregar_perfis(pasta: Path) -> dict[str, Perfil]:
    perfis: dict[str, Perfil] = {}
    for arquivo in sorted(pasta.glob("*.toml")):
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        instrucoes = (pasta / dados["instrucoes_arquivo"]).read_text(encoding="utf-8")
        agentes_cfg = dados.get("agentes", {})
        perfil = Perfil(
            nome=dados["nome"],
            descricao=dados.get("descricao", ""),
            extensoes=tuple(e.lower() for e in dados["extensoes"]),
            instrucoes=instrucoes,
            max_apontamentos=int(dados.get("max_apontamentos", 25)),
            ignorar_arquivos=tuple(dados.get("ignorar_arquivos", [])),
            nunca_ignorar=tuple(dados.get("nunca_ignorar", [])),
            agentes_por_risco={
                nivel: tuple(lista) for nivel, lista in agentes_cfg.items() if nivel != "modelo"
            },
            modelo_por_agente=dict(agentes_cfg.get("modelo", {})),
        )
        perfis[perfil.nome] = perfil
    if not perfis:
        raise ValueError(f"Nenhum perfil encontrado em {pasta}.")
    return perfis


@dataclass(frozen=True)
class Agente:
    nome: str
    instrucoes: str
    modelo_padrao: str = "sonnet"


_SECAO_APONTAR = "## O que apontar"
_SECAO_NAO_APONTAR = "## O que NÃO apontar"


def carregar_agentes(pasta: Path) -> dict[str, Agente]:
    """Lê perfis/agentes/<nome>.md; cada um precisa das duas seções obrigatórias. O conteúdo de
    REGRAS_COMUNS.md (se existir) é concatenado ao final de cada agente."""
    regras_comuns = ""
    caminho_comuns = pasta / "REGRAS_COMUNS.md"
    if caminho_comuns.exists():
        regras_comuns = caminho_comuns.read_text(encoding="utf-8")

    agentes: dict[str, Agente] = {}
    for arquivo in sorted(pasta.glob("*.md")):
        if arquivo.name == "REGRAS_COMUNS.md":
            continue
        texto = arquivo.read_text(encoding="utf-8")
        if _SECAO_APONTAR not in texto or _SECAO_NAO_APONTAR not in texto:
            raise ValueError(
                f"Agente '{arquivo.name}' precisa das seções '{_SECAO_APONTAR}' e '{_SECAO_NAO_APONTAR}'."
            )
        nome = arquivo.stem
        instrucoes = texto if not regras_comuns else f"{texto}\n\n{regras_comuns}"
        agentes[nome] = Agente(nome=nome, instrucoes=instrucoes)
    return agentes


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
    resumo_coordenador: str = ""
    erro: str = ""
    etapa: str = ""
    etapa_iniciada_em: str = ""
    atualizado_em: str = ""
    nivel_risco: str = ""
    arquivos_ignorados: str = ""
    workspace_aviso: str = ""
    criada_em: str = ""
    id: int | None = None


@dataclass(frozen=True)
class EventoRevisao:
    """Uma entrada no histórico de etapas de uma revisão (RF07)."""
    revisao_id: int
    etapa: str
    criado_em: str
    id: int | None = None


@dataclass
class ExecucaoAgente:
    """Estado vivo de um agente especialista durante um review (R6): diferente de EventoRevisao
    (log append-only), isto é uma linha que é atualizada conforme o agente progride."""
    revisao_id: int
    agente: str
    estado: str = "RODANDO"
    etapa: str = ""
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    achados_validos: int = 0
    achados_descartados: int = 0
    resposta_bruta: str = ""
    iniciado_em: str = ""
    atualizado_em: str = ""
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


@dataclass(frozen=True)
class GuiaArquitetura:
    """Resumo das ADRs (R: contexto de arquitetura no coordenador) — global, não por projeto."""
    projeto_fonte: str
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
