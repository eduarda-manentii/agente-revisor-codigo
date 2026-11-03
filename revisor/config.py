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


@dataclass(frozen=True)
class Config:
    gitlab_url: str
    gitlab_token: str
    gitlab_verificar_ssl: bool
    llm_provedor: str  # "claude-code" ou "api"
    anthropic_api_key: str
    claude_executavel: str
    modelo: str
    revisor_alvo: str
    projetos_treino: list[str]
    treino_desde: str
    banco: Path
    pasta_perfis: Path
    porta: int

    @property
    def host_gitlab(self) -> str:
        return urlparse(self.gitlab_url).netloc.lower()


def carregar_config() -> Config:
    load_dotenv(RAIZ / ".env")
    provedor = os.getenv("LLM_PROVEDOR", "claude-code").strip().lower()
    if provedor not in ("claude-code", "api"):
        raise ConfiguracaoInvalida("LLM_PROVEDOR deve ser 'claude-code' ou 'api'.")
    obrigatorias = ["GITLAB_URL", "GITLAB_TOKEN", "REVISOR_ALVO", "PROJETOS_TREINO"]
    if provedor == "api":
        obrigatorias.append("ANTHROPIC_API_KEY")
    faltando = [nome for nome in obrigatorias if not os.getenv(nome, "").strip()]
    if faltando:
        raise ConfiguracaoInvalida(
            "Preencha no arquivo .env: " + ", ".join(faltando) + " (veja o .env.example)."
        )
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
        revisor_alvo=os.environ["REVISOR_ALVO"].strip().lstrip("@"),
        projetos_treino=[p.strip() for p in os.environ["PROJETOS_TREINO"].split(",") if p.strip()],
        treino_desde=os.getenv("TREINO_DESDE", desde_padrao).strip(),
        banco=RAIZ / os.getenv("BANCO", "dados/revisor.db"),
        pasta_perfis=RAIZ / "perfis",
        porta=int(os.getenv("PORTA", "8765")),
    )
