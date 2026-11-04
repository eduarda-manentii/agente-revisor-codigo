"""Testes contra um repositório git real em tmp_path — sem rede nenhuma (tudo via file://)."""
import subprocess

import pytest

from revisor.adaptadores import workspace_git
from revisor.adaptadores.workspace_git import WorkspaceGit
from revisor.portas import ShaDivergente, WorkspaceIndisponivel

TOKEN_FALSO = "glpat-segredo-de-teste-xyz"


def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def origem(tmp_path):
    """Repositório de origem com 2 commits e uma ref de MR apontando pro segundo, como o GitLab
    exporia em refs/merge-requests/<iid>/head."""
    pasta = tmp_path / "grupo" / "projeto.git"
    pasta.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=pasta)
    _git("config", "user.email", "t@t.com", cwd=pasta)
    _git("config", "user.name", "t", cwd=pasta)
    (pasta / "A.java").write_text("v1\n", encoding="utf-8")
    _git("add", "A.java", cwd=pasta)
    _git("commit", "-q", "-m", "inicial", cwd=pasta)
    (pasta / "A.java").write_text("v1\nv2\n", encoding="utf-8")
    _git("add", "A.java", cwd=pasta)
    _git("commit", "-q", "-m", "mudanca do mr", cwd=pasta)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=pasta, capture_output=True, text=True,
                          check=True).stdout.strip()
    _git("update-ref", "refs/merge-requests/7/head", head, cwd=pasta)
    return pasta, head


@pytest.fixture
def adaptador(tmp_path):
    def fazer(**kw):
        return WorkspaceGit(
            gitlab_url=f"file://{tmp_path}", token=TOKEN_FALSO,
            pasta_repos=tmp_path / "cache", pasta_workspaces=tmp_path / "workspaces", **kw,
        )
    return fazer


def test_verificar_ssl_false_seta_git_ssl_no_verify(adaptador):
    ws = adaptador(verificar_ssl=False)
    assert ws._ambiente()["GIT_SSL_NO_VERIFY"] == "true"


def test_verificar_ssl_true_por_padrao_nao_mexe_na_variavel(adaptador):
    ws = adaptador()
    assert "GIT_SSL_NO_VERIFY" not in ws._ambiente()


def test_ambiente_usa_authorization_basic_para_o_protocolo_git(adaptador):
    # O protocolo git smart-HTTP do GitLab exige Basic Auth de verdade — não aceita o header
    # PRIVATE-TOKEN da API REST. Ver comentário em WorkspaceGit._ambiente.
    import base64
    ws = adaptador()
    valor = ws._ambiente()["GIT_CONFIG_VALUE_0"]
    assert valor.startswith("Authorization: Basic ")
    credenciais = base64.b64decode(valor.removeprefix("Authorization: Basic ")).decode()
    assert credenciais == f"oauth2:{TOKEN_FALSO}"


def test_ambiente_desliga_askpass_grafico_herdado(adaptador, monkeypatch):
    # Simula o terminal integrado do VS Code injetando seu próprio askpass gráfico no ambiente: o
    # adaptador precisa sobrescrever isso, senão o git fica esperando uma resposta que nunca vem.
    monkeypatch.setenv("GIT_ASKPASS", "/usr/share/code/resources/app/extensions/git/dist/askpass.sh")
    monkeypatch.setenv("SSH_ASKPASS", "/usr/share/code/resources/app/extensions/git/dist/askpass-main.js")
    ws = adaptador()
    ambiente = ws._ambiente()
    assert ambiente["GIT_ASKPASS"] == "echo"
    assert ambiente["SSH_ASKPASS"] == "echo"
    assert ambiente["GIT_ASKPASS_REQUIRE"] == "never"


def test_comando_travado_falha_apos_timeout_em_vez_de_pendurar(adaptador, origem):
    def executar_que_trava(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw.get("timeout"))

    ws = adaptador(executar=executar_que_trava, timeout_segundos=0.01)
    with pytest.raises(WorkspaceIndisponivel, match="não respondeu"):
        ws.preparar("grupo/projeto", 7, "qualquer")


def test_preparar_le_e_descarta(adaptador, origem):
    _, head = origem
    ws = adaptador()
    workspace = ws.preparar("grupo/projeto", 7, head)
    assert ws.ler_arquivo(workspace, "A.java") == "v1\nv2\n"
    assert ws.ler_arquivo(workspace, "nao-existe.txt") is None

    ws.descartar(workspace)
    assert not workspace.caminho.exists()
    lista = subprocess.run(["git", "-C", str(workspace.repo_cache), "worktree", "list"],
                           capture_output=True, text=True, check=True).stdout
    assert str(workspace.caminho) not in lista


def test_segunda_chamada_nao_re_clona(adaptador, origem, tmp_path):
    _, head = origem
    chamadas_clone = []

    def executar_espiao(args, **kw):
        if "clone" in args:
            chamadas_clone.append(args)
        return subprocess.run(args, **kw)

    ws = adaptador(executar=executar_espiao)
    w1 = ws.preparar("grupo/projeto", 7, head)
    ws.descartar(w1)
    w2 = ws.preparar("grupo/projeto", 7, head)
    ws.descartar(w2)
    assert len(chamadas_clone) == 1


def test_sha_divergente_nao_cria_worktree(adaptador, origem, tmp_path):
    ws = adaptador()
    with pytest.raises(ShaDivergente):
        ws.preparar("grupo/projeto", 7, "0000000000000000000000000000000000000000")
    assert not (tmp_path / "workspaces").exists() or not list((tmp_path / "workspaces").iterdir())


def test_git_ausente_levanta_workspace_indisponivel(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_git.shutil, "which", lambda exe: None)
    with pytest.raises(WorkspaceIndisponivel, match="não encontrado"):
        WorkspaceGit("file:///x", "t", tmp_path / "a", tmp_path / "b")


def test_clone_de_projeto_inexistente_cai_em_workspace_indisponivel(adaptador, tmp_path):
    ws = adaptador()
    with pytest.raises(WorkspaceIndisponivel):
        ws.preparar("grupo/nao-existe", 1, "qualquer")


def test_escrever_contexto_grava_patches_e_markdown(adaptador, origem):
    _, head = origem
    ws = adaptador()
    workspace = ws.preparar("grupo/projeto", 7, head)
    try:
        ws.escrever_contexto(workspace, {"A.java": "conteudo do patch"}, "# contexto")
        assert (workspace.caminho / ".revisor" / "diff" / "A.java.patch").read_text() == "conteudo do patch"
        assert (workspace.caminho / ".revisor" / "contexto-mr.md").read_text() == "# contexto"
    finally:
        ws.descartar(workspace)


def test_token_nunca_aparece_no_git_config_nem_na_saida_capturada(adaptador, origem, tmp_path):
    saidas_capturadas = []

    def executar_espiao(args, **kw):
        resultado = subprocess.run(args, **kw)
        saidas_capturadas.append((resultado.stdout or "") + (resultado.stderr or ""))
        return resultado

    _, head = origem
    ws = adaptador(executar=executar_espiao)
    workspace = ws.preparar("grupo/projeto", 7, head)
    try:
        config = (workspace.repo_cache / "config").read_text(encoding="utf-8")
        assert TOKEN_FALSO not in config
    finally:
        ws.descartar(workspace)
    assert all(TOKEN_FALSO not in saida for saida in saidas_capturadas)
