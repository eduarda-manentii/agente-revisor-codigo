"""Adaptador do workspace (R1): clona/atualiza um cache --bare por projeto e cria um worktree local
no head_sha exato do MR, via subprocess de git. O token nunca vai pra URL, pra .git/config nem pra
linha de comando: é passado como header HTTP via variável de ambiente do processo."""
from __future__ import annotations

import base64
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
        timeout_segundos: float = 180,
        executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._base_url = gitlab_url.rstrip("/")
        self._token = token
        self._pasta_repos = pasta_repos
        self._pasta_workspaces = pasta_workspaces
        self._verificar_ssl = verificar_ssl
        self._timeout = timeout_segundos
        self._executar = executar
        self._git = shutil.which("git")
        if self._git is None:
            raise WorkspaceIndisponivel("Comando 'git' não encontrado no PATH.")

    def _ambiente(self) -> dict:
        # O protocolo git smart-HTTP do GitLab (/<projeto>.git/info/refs etc.) não aceita o header
        # PRIVATE-TOKEN da API REST — ele exige HTTP Basic Auth de verdade (usuário qualquer +
        # personal access token como senha, mesmo esquema que o GITLAB_TOKEN já é). Por isso o header
        # vai como "Authorization: Basic <base64(usuário:token)>" em vez de PRIVATE-TOKEN.
        credenciais = base64.b64encode(f"oauth2:{self._token}".encode()).decode()
        ambiente = {
            **os.environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credenciais}",
            "GIT_TERMINAL_PROMPT": "0",
            # GIT_TERMINAL_PROMPT=0 só desliga o prompt do próprio git no terminal. Se o processo
            # herdar GIT_ASKPASS/SSH_ASKPASS de fora (ex.: o terminal integrado do VS Code injeta um
            # askpass gráfico próprio), o git ainda tenta esse caminho e fica esperando uma resposta
            # que nunca vem — trava pra sempre em vez de falhar rápido. "echo" devolve uma resposta
            # vazia na hora: sem credencial nenhuma, então falha rápido (ou nem é chamado, já que o
            # header acima já autentica) em vez de pendurar o review indefinidamente.
            "GIT_ASKPASS": "echo",
            "SSH_ASKPASS": "echo",
            "GIT_ASKPASS_REQUIRE": "never",
        }
        if not self._verificar_ssl:
            # Mesmo caso do GITLAB_VERIFICAR_SSL=false do adaptador da API: certificado interno.
            ambiente["GIT_SSL_NO_VERIFY"] = "true"
        return ambiente

    def _rodar(self, *args: str, cwd: Path | None = None) -> str:
        try:
            resultado = self._executar(
                [self._git, *args], cwd=cwd, env=self._ambiente(), capture_output=True, text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            # Segunda linha de defesa além do GIT_ASKPASS=echo: se o git travar esperando qualquer
            # outra coisa (rede lenta, proxy, etc.), falha de forma visível em vez de pendurar o
            # review pro resto da vida.
            raise WorkspaceIndisponivel(
                f"git {args[0]} não respondeu em {self._timeout:.0f}s (processo travado)."
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
