"""Adaptador do workspace (R1): clona/atualiza um cache --bare por projeto e cria um worktree local
no head_sha exato do MR, via subprocess de git. O token nunca vai pra URL, pra .git/config nem pra
linha de comando: é passado como header HTTP via variável de ambiente do processo."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from revisor.portas import ShaDivergente, Workspace, WorkspaceIndisponivel


class WorkspaceGit:
    def __init__(
        self,
        gitlab_url: str,
        token: str,
        pasta_repos: Path,
        pasta_workspaces: Path,
        verificar_ssl: bool = True,
        executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._base_url = gitlab_url.rstrip("/")
        self._token = token
        self._pasta_repos = pasta_repos
        self._pasta_workspaces = pasta_workspaces
        self._verificar_ssl = verificar_ssl
        self._executar = executar
        self._git = shutil.which("git")
        if self._git is None:
            raise WorkspaceIndisponivel("Comando 'git' não encontrado no PATH.")

    def _ambiente(self) -> dict:
        ambiente = {
            **os.environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"PRIVATE-TOKEN: {self._token}",
            "GIT_TERMINAL_PROMPT": "0",
        }
        if not self._verificar_ssl:
            # Mesmo caso do GITLAB_VERIFICAR_SSL=false do adaptador da API: certificado interno.
            ambiente["GIT_SSL_NO_VERIFY"] = "true"
        return ambiente

    def _rodar(self, *args: str, cwd: Path | None = None) -> str:
        resultado = self._executar(
            [self._git, *args], cwd=cwd, env=self._ambiente(), capture_output=True, text=True,
        )
        if resultado.returncode != 0:
            raise WorkspaceIndisponivel(f"git {args[0]} falhou: {(resultado.stderr or '').strip()[:300]}")
        return (resultado.stdout or "").strip()

    def _cache(self, projeto: str) -> Path:
        return self._pasta_repos / projeto.replace("/", "__")

    def preparar(self, projeto: str, mr_iid: int, head_sha: str) -> Workspace:
        cache = self._cache(projeto)
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            url = f"{self._base_url}/{projeto}.git"
            self._rodar("clone", "-q", "--bare", url, str(cache))

        ref_local = f"refs/revisor/mr-{mr_iid}"
        self._rodar("fetch", "-q", "origin", f"refs/merge-requests/{mr_iid}/head:{ref_local}", cwd=cache)
        sha_buscado = self._rodar("rev-parse", ref_local, cwd=cache)
        if sha_buscado != head_sha:
            raise ShaDivergente(
                f"O commit buscado ({sha_buscado[:8]}) não bate com o head_sha do GitLab ({head_sha[:8]})."
            )

        destino = self._pasta_workspaces / f"review-{mr_iid}-{head_sha[:8]}"
        if destino.exists():
            self._executar(
                [self._git, "-C", str(cache), "worktree", "remove", "--force", str(destino)],
                env=self._ambiente(), capture_output=True, text=True,
            )
            shutil.rmtree(destino, ignore_errors=True)
        self._pasta_workspaces.mkdir(parents=True, exist_ok=True)
        self._rodar("worktree", "add", "-q", "--detach", str(destino), ref_local, cwd=cache)
        return Workspace(caminho=destino, repo_cache=cache)

    def ler_arquivo(self, workspace: Workspace, caminho: str) -> str | None:
        alvo = workspace.caminho / caminho
        try:
            return alvo.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            return None

    def escrever_contexto(self, workspace: Workspace, patches: dict[str, str], contexto_md: str) -> None:
        pasta_diff = workspace.caminho / ".revisor" / "diff"
        for caminho, conteudo in patches.items():
            destino = pasta_diff / f"{caminho}.patch"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(conteudo, encoding="utf-8")
        (workspace.caminho / ".revisor" / "contexto-mr.md").write_text(contexto_md, encoding="utf-8")

    def descartar(self, workspace: Workspace) -> None:
        self._executar(
            [self._git, "-C", str(workspace.repo_cache), "worktree", "remove", "--force", str(workspace.caminho)],
            env=self._ambiente(), capture_output=True, text=True,
        )
        shutil.rmtree(workspace.caminho, ignore_errors=True)
