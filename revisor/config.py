"""Configuração lida do arquivo .env (nunca versionado)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


class ConfiguracaoInvalida(Exception):
    pass


def _lista(valor: str) -> list[str]:
    return [p.strip().strip("/") for p in valor.split(",") if p.strip().strip("/")]


@dataclass(frozen=True)
class Config:
    gitlab_url: str
    gitlab_token: str
    gitlab_verificar_ssl: bool
    llm_provedor: str  # "claude-code" ou "api"
    anthropic_api_key: str
    claude_executavel: str
    modelo: str
    grupos_treino: list[str]
    projetos_treino: list[str]
    revisores_excluidos: frozenset[str]
    min_comentarios_guia_micro: int
    mapa_validade_dias: int
    adr_projeto: str
    adr_caminho: str
    adr_validade_dias: int
    limite_inatividade_segundos: int
    agentes_paralelos: int
    limite_turnos_agente: int
    treino_desde: str
    banco: Path
    pasta_perfis: Path
    pasta_repos: Path
    pasta_workspaces: Path
    porta: int

    @property
    def host_gitlab(self) -> str:
        return urlparse(self.gitlab_url).netloc.lower()


def carregar_config() -> Config:
    load_dotenv(RAIZ / ".env")
    provedor = os.getenv("LLM_PROVEDOR", "claude-code").strip().lower()
    if provedor not in ("claude-code", "api"):
        raise ConfiguracaoInvalida("LLM_PROVEDOR deve ser 'claude-code' ou 'api'.")
    obrigatorias = ["GITLAB_URL", "GITLAB_TOKEN"]
    if provedor == "api":
        obrigatorias.append("ANTHROPIC_API_KEY")
    faltando = [nome for nome in obrigatorias if not os.getenv(nome, "").strip()]
    if faltando:
        raise ConfiguracaoInvalida(
            "Preencha no arquivo .env: " + ", ".join(faltando) + " (veja o .env.example)."
        )
    grupos = _lista(os.getenv("GRUPOS_TREINO", ""))
    projetos = _lista(os.getenv("PROJETOS_TREINO", ""))
    if not grupos and not projetos:
        raise ConfiguracaoInvalida("Preencha GRUPOS_TREINO e/ou PROJETOS_TREINO no .env.")
    desde_padrao = (date.today() - timedelta(days=365)).isoformat()
    return Config(
        gitlab_url=os.environ["GITLAB_URL"].strip().rstrip("/"),
        gitlab_token=os.environ["GITLAB_TOKEN"].strip(),
        gitlab_verificar_ssl=os.getenv("GITLAB_VERIFICAR_SSL", "true").strip().lower() != "false",
        llm_provedor=provedor,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        claude_executavel=os.getenv("CLAUDE_EXECUTAVEL", "claude").strip(),
        # Vazio = modelo padrão do Claude Code (claude-code) / obrigatório na API.
        modelo=os.getenv("LLM_MODELO", "" if provedor == "claude-code" else "claude-sonnet-5-5").strip(),
        grupos_treino=grupos,
        projetos_treino=projetos,
        revisores_excluidos=frozenset(
            u.strip().lstrip("@") for u in os.getenv("REVISORES_EXCLUIDOS", "").split(",") if u.strip()
        ),
        min_comentarios_guia_micro=int(os.getenv("MIN_COMENTARIOS_GUIA_MICRO", "30")),
        mapa_validade_dias=int(os.getenv("MAPA_VALIDADE_DIAS", "30")),
        adr_projeto=os.getenv("ADR_PROJETO", "").strip().strip("/"),
        adr_caminho=os.getenv("ADR_CAMINHO", "").strip().strip("/"),
        adr_validade_dias=int(os.getenv("ADR_VALIDADE_DIAS", "30")),
        limite_inatividade_segundos=int(os.getenv("LIMITE_INATIVIDADE_SEGUNDOS", "60")),
        agentes_paralelos=int(os.getenv("AGENTES_PARALELOS", "2")),
        limite_turnos_agente=int(os.getenv("LIMITE_TURNOS_AGENTE", "15")),
        treino_desde=os.getenv("TREINO_DESDE", desde_padrao).strip(),
        banco=RAIZ / os.getenv("BANCO", "dados/revisor.db"),
        pasta_perfis=RAIZ / "perfis",
        pasta_repos=RAIZ / "dados" / "repos",
        pasta_workspaces=RAIZ / "dados" / "workspaces",
        porta=int(os.getenv("PORTA", "8765")),
    )
