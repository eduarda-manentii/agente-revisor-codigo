"""Ponto de entrada: python -m revisor"""
from __future__ import annotations

import logging
import sys

import uvicorn

from revisor.adaptadores.banco import RepositorioSQLite
from revisor.adaptadores.gitlab_adapter import GitLabAdapter
from revisor.adaptadores.llm_anthropic import LLMAnthropic
from revisor.adaptadores.llm_claude_code import ErroClaudeCode, LLMClaudeCode
from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.config import ConfiguracaoInvalida, carregar_config
from revisor.dominio.modelos import carregar_perfis
from revisor.web.app import Servicos, criar_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = carregar_config()
    except ConfiguracaoInvalida as e:
        sys.exit(f"Configuração incompleta: {e}")

    repo = RepositorioSQLite(cfg.banco)
    repo.marcar_execucoes_interrompidas()
    perfis = carregar_perfis(cfg.pasta_perfis)
    gitlab = GitLabAdapter(cfg.gitlab_url, cfg.gitlab_token, cfg.gitlab_verificar_ssl)
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
        revisar=RevisarMR(gitlab, llm, repo, perfis, cfg.host_gitlab),
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
