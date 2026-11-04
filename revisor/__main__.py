"""Ponto de entrada: python -m revisor"""
from __future__ import annotations

import logging
import sys

import uvicorn

from revisor.adaptadores.agente_claude_code import AgenteClaudeCode, ErroAgente
from revisor.adaptadores.banco import RepositorioSQLite
from revisor.adaptadores.coordenador_claude_code import CoordenadorClaudeCode, ErroCoordenador
from revisor.adaptadores.gitlab_adapter import GitLabAdapter
from revisor.adaptadores.llm_anthropic import LLMAnthropic
from revisor.adaptadores.llm_claude_code import ErroClaudeCode, LLMClaudeCode
from revisor.adaptadores.workspace_git import WorkspaceGit
from revisor.aplicacao.executar_agentes import ExecutarAgentes
from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.config import ConfiguracaoInvalida, carregar_config
from revisor.dominio.modelos import carregar_agentes, carregar_perfis
from revisor.portas import Workspace, WorkspaceIndisponivel
from revisor.web.app import Servicos, criar_app


class _SemWorkspace:
    """Usado só quando o git não está instalado: os agentes não têm como ler o código (R1 é
    pré-requisito do R3), então a avaliação não roda, mas o app sobe e o resto funciona."""

    def preparar(self, projeto: str, mr_iid: int, head_sha: str) -> Workspace:
        raise WorkspaceIndisponivel("git não está instalado nesta máquina.")

    def ler_arquivo(self, workspace: Workspace, caminho: str) -> str | None:
        return None

    def escrever_contexto(self, workspace: Workspace, patches: dict, contexto_md: str) -> None:
        pass

    def descartar(self, workspace: Workspace) -> None:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = carregar_config()
    except ConfiguracaoInvalida as e:
        sys.exit(f"Configuração incompleta: {e}")

    repo = RepositorioSQLite(cfg.banco)
    repo.marcar_execucoes_interrompidas()
    perfis = carregar_perfis(cfg.pasta_perfis)
    agentes = carregar_agentes(cfg.pasta_perfis / "agentes")
    gitlab = GitLabAdapter(cfg.gitlab_url, cfg.gitlab_token, cfg.gitlab_verificar_ssl)
    try:
        workspace = WorkspaceGit(cfg.gitlab_url, cfg.gitlab_token, cfg.pasta_repos, cfg.pasta_workspaces,
                                 verificar_ssl=cfg.gitlab_verificar_ssl)
    except WorkspaceIndisponivel as e:
        logging.warning("Workspace do repositório indisponível (%s); a avaliação de MR não vai funcionar.", e)
        workspace = _SemWorkspace()
    # Agentes e coordenador (R3/R4) sempre usam o Claude Code local (claude -p), independente do
    # LLM_PROVEDOR escolhido — isso é fixo na arquitetura do v3, só o treino aceita a API.
    try:
        agente_porta = AgenteClaudeCode(cfg.claude_executavel, limite_turnos=cfg.limite_turnos_agente)
        coordenador = CoordenadorClaudeCode(cfg.claude_executavel)
    except (ErroAgente, ErroCoordenador) as e:
        sys.exit(str(e))
    executar_agentes = ExecutarAgentes(agente_porta, repo, agentes, agentes_paralelos=cfg.agentes_paralelos)

    if cfg.llm_provedor == "api":
        llm = LLMAnthropic(cfg.anthropic_api_key, cfg.modelo)
    else:
        try:
            llm = LLMClaudeCode(cfg.claude_executavel, cfg.modelo)
        except ErroClaudeCode as e:
            sys.exit(str(e))

    servicos = Servicos(
        repo=repo,
        perfis=perfis,
        gitlab_url=cfg.gitlab_url,
        limite_inatividade_segundos=cfg.limite_inatividade_segundos,
        revisar=RevisarMR(gitlab, repo, perfis, cfg.host_gitlab, workspace, executar_agentes, coordenador),
        triar=TriarApontamento(repo),
        publicar=PublicarAprovados(gitlab, repo),
        treinar=TreinarPerfil(
            gitlab, llm, repo, perfis, cfg.grupos_treino, cfg.projetos_treino,
            cfg.revisores_excluidos, cfg.treino_desde,
            min_comentarios_guia_micro=cfg.min_comentarios_guia_micro,
            mapa_validade_dias=cfg.mapa_validade_dias,
        ),
    )
    print(f"\n  Revisor rodando em http://127.0.0.1:{cfg.porta}\n")
    # 127.0.0.1: só a sua máquina acessa. O token do GitLab tem poder de escrita.
    uvicorn.run(criar_app(servicos), host="127.0.0.1", port=cfg.porta, log_level="warning")


if __name__ == "__main__":
    main()
