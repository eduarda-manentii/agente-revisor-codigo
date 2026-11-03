import json
import subprocess

import pytest

from revisor.adaptadores import llm_claude_code
from revisor.adaptadores.llm_claude_code import ErroClaudeCode, LLMClaudeCode


class Executor:
    def __init__(self, stdout="", returncode=0, stderr="", excecao=None):
        self.resposta = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.excecao = excecao
        self.chamada = None

    def __call__(self, comando, **kw):
        sistema = open(comando[comando.index("--system-prompt-file") + 1], encoding="utf-8").read()
        self.chamada = {"comando": comando, "sistema": sistema, **kw}
        if self.excecao:
            raise self.excecao
        return self.resposta


@pytest.fixture(autouse=True)
def claude_instalado(monkeypatch):
    monkeypatch.setattr(llm_claude_code.shutil, "which", lambda exe: f"/usr/bin/{exe}")


def test_envia_prompt_por_stdin_sistema_por_arquivo_sem_ferramentas_e_sem_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-nao-deve-vazar")
    executor = Executor(json.dumps({"result": "[]", "is_error": False}))
    resposta = LLMClaudeCode(modelo="sonnet", executar=executor).completar("SISTEMA", "USUARIO")

    assert resposta == "[]"
    c = executor.chamada
    assert c["input"] == "USUARIO" and c["sistema"] == "SISTEMA"
    assert c["comando"][:2] == ["/usr/bin/claude", "-p"]
    assert c["comando"][c["comando"].index("--tools") + 1] == ""
    assert c["comando"][-2:] == ["--model", "sonnet"]
    assert "ANTHROPIC_API_KEY" not in c["env"]


def test_sem_modelo_usa_padrao_do_claude_code():
    executor = Executor(json.dumps({"result": "ok"}))
    LLMClaudeCode(executar=executor).completar("s", "u")
    assert "--model" not in executor.chamada["comando"]


@pytest.mark.parametrize("executor,trecho", [
    (Executor(json.dumps({"result": "Not logged in", "is_error": True}), returncode=1), "Not logged in"),
    (Executor("lixo", returncode=2, stderr="unknown option"), "unknown option"),
    (Executor(json.dumps({"sem": "result"})), "result"),
    (Executor(excecao=subprocess.TimeoutExpired("claude", 1)), "não respondeu"),
])
def test_erros_viram_mensagem_clara(executor, trecho):
    with pytest.raises(ErroClaudeCode, match=trecho):
        LLMClaudeCode(executar=executor).completar("s", "u")


def test_claude_nao_instalado(monkeypatch):
    monkeypatch.setattr(llm_claude_code.shutil, "which", lambda exe: None)
    with pytest.raises(ErroClaudeCode, match="não encontrado"):
        LLMClaudeCode()
