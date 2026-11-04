"""Interfaces (Protocols) entre os casos de uso e o mundo externo."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from revisor.dominio.agentes import ResultadoAgente
from revisor.dominio.apontamento import Apontamento
from revisor.dominio.coordenador import Descarte
from revisor.dominio.modelos import (
    GERAL,
    Agente,
    ComentarioHistorico,
    DadosMR,
    EventoRevisao,
    ExecucaoAgente,
    Exemplo,
    Guia,
    MapaProjeto,
    Revisao,
    Treino,
)


@dataclass(frozen=True)
class Posicao:
    base_sha: str
    start_sha: str
    head_sha: str
    caminho_antigo: str
    caminho_novo: str
    linha_nova: int
    linha_antiga: int | None


@dataclass(frozen=True)
class ArvoreProjeto:
    sha: str
    caminhos: tuple[str, ...]


class PortaGitLab(Protocol):
    def obter_mr(self, projeto: str, iid: int) -> DadosMR: ...

    def head_sha_atual(self, projeto: str, iid: int) -> str: ...

    def criar_comentario(self, projeto: str, iid: int, posicao: Posicao, corpo: str) -> str:
        """Cria a discussion inline e retorna o id dela."""
        ...

    def listar_projetos(self, grupo: str) -> list[str]:
        """path_with_namespace de todos os projetos do grupo (com subgrupos, sem arquivados), A-Z."""
        ...

    def listar_comentarios(
        self, projeto: str, desde: str, excluir_autores: set[str]
    ) -> Iterator[ComentarioHistorico]:
        """Comentários inline em MRs mergeados atualizados desde `desde` (ISO-8601).

        Ignora o autor do próprio MR (é ele respondendo, não revisando) e quem estiver em
        `excluir_autores`.
        """
        ...

    def obter_arvore(self, projeto: str) -> ArvoreProjeto:
        """SHA do branch padrão e todos os caminhos de arquivo (recursivo, sem diretórios)."""
        ...

    def obter_arquivo(self, projeto: str, caminho: str, ref: str) -> str | None:
        """Conteúdo completo do arquivo no ref dado, ou None se não existir/der erro."""
        ...


class PortaLLM(Protocol):
    def completar(self, sistema: str, usuario: str) -> str: ...


@dataclass(frozen=True)
class EventoAgente:
    """Um passo de progresso de um agente (R6), derivado do stream de eventos do Claude Code."""
    tipo: str  # "tool_use" | "resultado"
    descricao: str  # "Lendo src/X.java", "Buscando 'validarToken'", ...


class PortaAgente(Protocol):
    def executar(
        self, agente: Agente, workspace: Workspace, modelo: str,
        usuario: str, ao_progresso: Callable[[EventoAgente], None],
    ) -> ResultadoAgente:
        """Roda um agente especialista (processo isolado, só leitura no workspace, R3)."""
        ...


class PortaCoordenador(Protocol):
    def executar(
        self, workspace: Workspace, modelo: str, sistema: str, usuario: str,
        ao_progresso: Callable[[EventoAgente], None],
    ) -> str:
        """Roda o coordenador (processo isolado, só leitura no workspace, R4) e devolve o texto
        bruto da resposta — o parse fica em dominio/coordenador.py, puro e testável."""
        ...


@dataclass(frozen=True)
class Workspace:
    caminho: Path
    repo_cache: Path


class WorkspaceIndisponivel(Exception):
    """Clone/fetch falhou (rede, permissão, git ausente): o review continua em modo só diff (R1.5)."""


class ShaDivergente(Exception):
    """O commit buscado pela ref de MR não bate com o head_sha do GitLab: aborta o review (R1)."""


class PortaWorkspace(Protocol):
    def preparar(self, projeto: str, mr_iid: int, head_sha: str) -> Workspace:
        """Checkout local do MR no head_sha exato (worktree sobre um clone --bare em cache)."""
        ...

    def ler_arquivo(self, workspace: Workspace, caminho: str) -> str | None:
        """Conteúdo do arquivo no workspace, ou None se não existir."""
        ...

    def escrever_contexto(self, workspace: Workspace, patches: dict[str, str], contexto_md: str) -> None:
        """Grava .revisor/diff/<caminho>.patch e .revisor/contexto-mr.md (base para os agentes, R3)."""
        ...

    def descartar(self, workspace: Workspace) -> None:
        """Remove o worktree. Deve ser chamado sempre, mesmo em erro ou cancelamento."""
        ...


class Repositorio(Protocol):
    # revisões
    def criar_revisao(self, revisao: Revisao) -> int: ...
    def salvar_revisao(self, revisao: Revisao) -> None: ...
    def obter_revisao(self, revisao_id: int) -> Revisao: ...
    def listar_revisoes(self, limite: int = 30) -> list[Revisao]: ...
    def obter_revisao_anterior(self, projeto: str, mr_iid: int, antes_de: int) -> Revisao | None:
        """A revisão concluída mais recente do mesmo MR antes de `antes_de`, se houver."""
        ...
    def registrar_evento(self, revisao_id: int, etapa: str, criado_em: str) -> None:
        """Acrescenta uma entrada no histórico de etapas (RF07); não mexe na própria Revisao."""
        ...
    def listar_eventos(self, revisao_id: int) -> list[EventoRevisao]: ...

    # apontamentos
    def adicionar_apontamentos(self, apontamentos: list[Apontamento]) -> None: ...
    def salvar_apontamento(self, apontamento: Apontamento) -> None: ...
    def obter_apontamento(self, apontamento_id: int) -> Apontamento: ...
    def listar_apontamentos(self, revisao_id: int) -> list[Apontamento]: ...
    def listar_rejeitados_pendentes(self, perfil: str) -> list[Apontamento]:
        """Rejeitados que ainda não foram incorporados ao guia geral."""
        ...

    # treino
    def criar_treino(self, treino: Treino) -> int: ...
    def salvar_treino(self, treino: Treino) -> None: ...
    def obter_treino(self, treino_id: int) -> Treino: ...
    def ultimo_treino(self, perfil: str) -> Treino | None: ...
    def marcar_execucoes_interrompidas(self) -> None:
        """Revisões/treinos que ficaram PROCESSANDO (app fechado no meio) viram ERRO."""
        ...
    def checkpoint(self, perfil: str, projeto: str) -> str | None: ...
    def salvar_checkpoint(self, perfil: str, projeto: str, desde: str) -> None: ...
    def salvar_exemplo(self, exemplo: Exemplo) -> bool:
        """Retorna False se o exemplo já existia (deduplicação por perfil + note_id)."""
        ...
    def listar_exemplos(self, perfil: str, limite: int | None = None) -> list[Exemplo]: ...
    def listar_exemplos_pendentes(self, perfil: str, escopo: str) -> list[Exemplo]:
        """Exemplos ainda não incorporados à camada `escopo` (GERAL ou um projeto)."""
        ...
    def obter_exemplos(self, perfil: str, note_ids: list[int]) -> list[Exemplo]:
        """Preserva a ordem pedida e ignora note_ids inexistentes."""
        ...
    def contar_exemplos(self, perfil: str) -> int: ...
    def contar_exemplos_pendentes(self, perfil: str) -> int: ...
    def contar_exemplos_por_projeto(self, perfil: str) -> list[tuple[str, int]]: ...
    def salvar_guia(
        self, perfil: str, escopo: str, conteudo: str, note_ids: list[int], apontamento_ids: list[int]
    ) -> int:
        """Cria nova versão da camada `escopo` e marca os itens como incorporados, atomicamente."""
        ...
    def guia_ativo(self, perfil: str, escopo: str = GERAL) -> Guia | None: ...
    def guia_por_versao(self, perfil: str, versao: int, escopo: str = GERAL) -> Guia | None: ...
    def listar_versoes_guia(self, perfil: str, escopo: str = GERAL) -> list[Guia]: ...
    def listar_escopos_guia(self, perfil: str) -> list[str]:
        """Projetos (escopos != GERAL) que já têm ao menos uma versão de guia."""
        ...

    # mapas técnicos
    def salvar_mapa(self, mapa: MapaProjeto) -> int: ...
    def mapa_ativo(self, projeto: str) -> MapaProjeto | None: ...
    def listar_mapas(self) -> list[MapaProjeto]:
        """O mapa mais recente de cada projeto."""
        ...

    # execução dos agentes especialistas (R6)
    def salvar_execucao_agente(self, execucao: ExecucaoAgente) -> int:
        """Upsert por (revisao_id, agente): cria na primeira chamada, atualiza nas seguintes."""
        ...
    def listar_execucoes_agentes(self, revisao_id: int) -> list[ExecucaoAgente]: ...

    # descartes do coordenador (R4)
    def salvar_descartes(self, revisao_id: int, descartes: list[Descarte]) -> None: ...
    def listar_descartes(self, revisao_id: int, incluir_recuperados: bool = False) -> list[Descarte]: ...
    def obter_descarte(self, descarte_id: int) -> Descarte: ...
    def marcar_descarte_recuperado(self, descarte_id: int) -> None: ...
