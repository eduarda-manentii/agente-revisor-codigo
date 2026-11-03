"""Adaptador GitLab usando python-gitlab. Toda chamada de rede ao GitLab passa por aqui."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterator

import gitlab
from gitlab.exceptions import GitlabError, GitlabHttpError

from revisor.dominio.diff import ArquivoDiff, parse_hunks
from revisor.dominio.modelos import ComentarioHistorico, DadosMR
from revisor.portas import ArvoreProjeto, Posicao

log = logging.getLogger(__name__)

_CONTEXTO_TRECHO = 5


class GitLabAdapter:
    def __init__(self, url: str, token: str, verificar_ssl: bool = True) -> None:
        self._gl = gitlab.Gitlab(
            url, private_token=token, ssl_verify=verificar_ssl,
            retry_transient_errors=True, timeout=60,
        )

    @lru_cache(maxsize=64)
    def _projeto(self, caminho: str) -> Any:
        return self._gl.projects.get(caminho)

    # ---------- descoberta ----------
    def listar_projetos(self, grupo: str) -> list[str]:
        g = self._gl.groups.get(grupo)
        projetos = g.projects.list(include_subgroups=True, archived=False, iterator=True)
        return sorted(p.path_with_namespace for p in projetos)

    # ---------- review ----------
    def obter_mr(self, projeto: str, iid: int) -> DadosMR:
        p = self._projeto(projeto)
        mr = p.mergerequests.get(iid)
        refs = mr.diff_refs or {}
        if not refs.get("head_sha"):
            raise ValueError("O GitLab não retornou os SHAs do diff deste MR (diff_refs vazio).")
        arquivos = tuple(self._para_arquivo(d) for d in self._diffs(p, mr))
        return DadosMR(
            titulo=mr.title or "",
            descricao=mr.description or "",
            base_sha=refs["base_sha"],
            start_sha=refs["start_sha"],
            head_sha=refs["head_sha"],
            arquivos=arquivos,
        )

    def _diffs(self, p: Any, mr: Any) -> list[dict]:
        # /diffs (GitLab >= 15.7) pagina e não trunca; /changes é o fallback para versões antigas.
        try:
            return list(self._gl.http_list(
                f"/projects/{p.id}/merge_requests/{mr.iid}/diffs", get_all=True
            ))
        except GitlabHttpError as erro:
            if erro.response_code != 404:
                raise
            log.info("Endpoint /diffs indisponível; usando /changes.")
            dados = mr.changes()
            if dados.get("overflow"):
                log.warning("MR grande: o GitLab truncou a lista de arquivos em /changes.")
            return dados.get("changes", [])

    @staticmethod
    def _para_arquivo(d: dict) -> ArquivoDiff:
        return ArquivoDiff(
            caminho_antigo=d.get("old_path") or d.get("new_path", ""),
            caminho_novo=d.get("new_path") or d.get("old_path", ""),
            linhas=parse_hunks(d.get("diff") or ""),
            removido=bool(d.get("deleted_file")),
        )

    def head_sha_atual(self, projeto: str, iid: int) -> str:
        mr = self._projeto(projeto).mergerequests.get(iid)
        return (mr.diff_refs or {}).get("head_sha", "")

    def criar_comentario(self, projeto: str, iid: int, posicao: Posicao, corpo: str) -> str:
        position: dict[str, Any] = {
            "position_type": "text",
            "base_sha": posicao.base_sha,
            "start_sha": posicao.start_sha,
            "head_sha": posicao.head_sha,
            "old_path": posicao.caminho_antigo,
            "new_path": posicao.caminho_novo,
            "new_line": posicao.linha_nova,
        }
        if posicao.linha_antiga is not None:  # linha de contexto exige as duas
            position["old_line"] = posicao.linha_antiga
        mr = self._projeto(projeto).mergerequests.get(iid, lazy=True)
        discussion = mr.discussions.create({"body": corpo, "position": position})
        return str(discussion.id)

    # ---------- treino: comentários ----------
    def listar_comentarios(
        self, projeto: str, desde: str, excluir_autores: set[str]
    ) -> Iterator[ComentarioHistorico]:
        p = self._projeto(projeto)
        for mr in p.mergerequests.list(state="merged", updated_after=desde, iterator=True):
            autor_mr = (mr.author or {}).get("username", "")
            for discussion in mr.discussions.list(iterator=True):
                notas = discussion.attributes.get("notes") or []
                resolvido = any(n.get("resolved") for n in notas)
                for nota in notas:
                    if nota.get("system") or nota.get("type") != "DiffNote":
                        continue
                    autor_nota = (nota.get("author") or {}).get("username", "")
                    if autor_nota == autor_mr or autor_nota in excluir_autores:
                        continue
                    yield self._para_comentario(p, projeto, mr.iid, nota, resolvido, autor_nota)

    def _para_comentario(
        self, p: Any, projeto: str, mr_iid: int, nota: dict, resolvido: bool, autor: str
    ) -> ComentarioHistorico:
        pos = nota.get("position") or {}
        if pos.get("new_line"):
            arquivo, linha, ref = pos.get("new_path", ""), pos["new_line"], pos.get("head_sha")
        else:  # comentário em linha removida: o código está na versão base
            arquivo, linha, ref = pos.get("old_path", ""), pos.get("old_line"), pos.get("base_sha")
        trecho = self._trecho(p.id, arquivo, ref, linha) if (ref and linha) else ""
        return ComentarioHistorico(
            projeto=projeto, mr_iid=mr_iid, note_id=int(nota["id"]), arquivo=arquivo,
            linha=linha, comentario=nota.get("body", ""), resolvido=resolvido,
            autor=autor, criado_em=nota.get("created_at", "") or "", trecho=trecho,
        )

    @lru_cache(maxsize=512)
    def _ler_arquivo(self, projeto_id: int, caminho: str, ref: str) -> str | None:
        try:
            p = self._gl.projects.get(projeto_id, lazy=True)
            conteudo = p.files.raw(file_path=caminho, ref=ref)
        except GitlabError as erro:
            log.info("Não foi possível ler %s@%s: %s", caminho, ref, erro)
            return None
        return bytes(conteudo).decode("utf-8", errors="replace")

    def _trecho(self, projeto_id: int, caminho: str, ref: str, linha: int) -> str:
        conteudo = self._ler_arquivo(projeto_id, caminho, ref)
        if not conteudo:
            return ""
        linhas = conteudo.splitlines()
        inicio = max(1, linha - _CONTEXTO_TRECHO)
        fim = min(len(linhas), linha + _CONTEXTO_TRECHO)
        return "\n".join(
            f"{'>' if n == linha else ' '}{n:>5} {linhas[n - 1]}" for n in range(inicio, fim + 1)
        )

    # ---------- mapa técnico ----------
    def obter_arvore(self, projeto: str) -> ArvoreProjeto:
        p = self._projeto(projeto)
        default_branch = p.default_branch
        if not default_branch:
            raise ValueError(f"Projeto {projeto} não tem branch padrão.")
        branch = p.branches.get(default_branch)
        sha = branch.commit["id"]
        itens = p.repository_tree(ref=sha, recursive=True, iterator=True)
        caminhos = tuple(i["path"] for i in itens if i.get("type") == "blob")
        return ArvoreProjeto(sha=sha, caminhos=caminhos)

    def obter_arquivo(self, projeto: str, caminho: str, ref: str) -> str | None:
        return self._ler_arquivo(self._projeto(projeto).id, caminho, ref)
