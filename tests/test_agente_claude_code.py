"""Testa o adaptador de agente com processo falso e relógio falso — determinístico, sem subprocess
de verdade e sem rede."""
import json

import pytest

from revisor.adaptadores import agente_claude_code
from revisor.adaptadores.agente_claude_code import AgenteClaudeCode, ErroAgente, montar_argumentos
from revisor.dominio.modelos import Agente
from revisor.portas import Workspace


def evento_tool_use(nome="Read", entrada=None) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": nome, "input": entrada or {"file_path": "A.java"}}]},
    })


def evento_resultado(texto: str, is_error: bool = False) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "result": texto})


class RelogioFalso:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


class ProcessoFalso:
    """`eventos`: lista de (segundos de espera antes da linha, linha ou None pra EOF)."""

    def __init__(self, eventos: list, relogio: RelogioFalso) -> None:
        self._eventos = list(eventos)
        self._relogio = relogio
        self.encerrado = False

    def proxima_linha(self, timeout: float):
        if not self._eventos:
            return None
        espera, linha = self._eventos[0]
        if espera > timeout:
            self._relogio.avancar(timeout)
            self._eventos[0] = (espera - timeout, linha)
            raise TimeoutError
        self._relogio.avancar(espera)
        self._eventos.pop(0)
        return linha

    def stderr(self) -> str:
        return ""

    def encerrar(self) -> None:
        self.encerrado = True


@pytest.fixture(autouse=True)
def claude_instalado(monkeypatch):
    monkeypatch.setattr(agente_claude_code.shutil, "which", lambda exe: f"/usr/bin/{exe}")


def fabrica(scripts: list[list]):
    """Cada chamada de `executar_processo` consome o próximo script da lista."""
    relogio = RelogioFalso()
    restantes = [list(s) for s in scripts]
    processos: list[ProcessoFalso] = []

    def abrir(comando, cwd, entrada):
        p = ProcessoFalso(restantes.pop(0), relogio)
        processos.append(p)
        return p

    return abrir, relogio, processos


AGENTE = Agente(nome="qualidade", instrucoes="instruções do agente")
WS = Workspace(caminho="/fake/ws", repo_cache="/fake/cache")


def test_montar_argumentos_e_funcao_pura():
    args = montar_argumentos("/usr/bin/claude", "sonnet", "/tmp/sistema.md", "/tmp/ws")
    assert args == [
        "/usr/bin/claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--restricted",
        "--tools", "Read,Grep,Glob",
        "--add-dir", "/tmp/ws",
        "--system-prompt-file", "/tmp/sistema.md",
        "--model", "sonnet",
    ]


def test_claude_nao_instalado(monkeypatch):
    monkeypatch.setattr(agente_claude_code.shutil, "which", lambda exe: None)
    with pytest.raises(ErroAgente, match="não encontrado"):
        AgenteClaudeCode()


def test_achados_validos_e_progresso_chamado_por_tool_use():
    achado = {"arquivo": "A.java", "linha": 1, "severidade": "P1", "confianca": 8,
              "comentario": "x", "evidencia": "y"}
    script = [
        (0, evento_tool_use("Read", {"file_path": "A.java"})),
        (0, evento_tool_use("Grep", {"pattern": "validarToken"})),
        (0, evento_resultado(json.dumps([achado]))),
    ]
    abrir, relogio, _ = fabrica([script])
    eventos_progresso = []
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", eventos_progresso.append)

    assert resultado.erro == ""
    assert len(resultado.achados) == 1
    descricoes = [e.descricao for e in eventos_progresso]
    assert "Lendo A.java" in descricoes
    assert "Buscando 'validarToken'" in descricoes
    assert "Concluído" in descricoes


def test_limite_de_turnos_encerra_o_processo():
    script = [(0, evento_tool_use()) for _ in range(20)]
    abrir, relogio, processos = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio, limite_turnos=15)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert "turnos" in resultado.erro.lower()
    assert processos[0].encerrado is True


def test_sem_primeiro_evento_no_prazo():
    script = [(61, evento_resultado("[]"))]
    abrir, relogio, processos = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio, timeout_primeiro_evento=60)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert "não iniciou" in resultado.erro
    assert processos[0].encerrado is True


def test_sem_evento_durante_execucao():
    script = [(0, evento_tool_use()), (181, evento_resultado("[]"))]
    abrir, relogio, processos = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio, timeout_sem_evento=180)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert "sem resposta" in resultado.erro
    assert processos[0].encerrado is True


def test_timeout_total_do_agente():
    # heartbeats frequentes (nunca estouram sozinhos), mas a soma passa do timeout total
    script = [(100, evento_tool_use()) for _ in range(5)]
    abrir, relogio, processos = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio, timeout_primeiro_evento=200,
                          timeout_sem_evento=180, timeout_agente_padrao=300)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert "esgotado" in resultado.erro
    assert processos[0].encerrado is True


def test_json_invalido_tenta_de_novo_uma_vez_e_depois_falha():
    script_ruim = [(0, evento_resultado("isso não é json nenhum"))]
    abrir, relogio, processos = fabrica([script_ruim, script_ruim])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert "inválida" in resultado.erro.lower()
    assert len(processos) == 2  # tentou de novo


def test_json_invalido_na_primeira_e_valido_na_segunda():
    achado = {"arquivo": "A.java", "linha": 1, "severidade": "P1", "confianca": 8,
              "comentario": "x", "evidencia": "y"}
    ruim = [(0, evento_resultado("lixo"))]
    bom = [(0, evento_resultado(json.dumps([achado])))]
    abrir, relogio, processos = fabrica([ruim, bom])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert resultado.erro == ""
    assert len(resultado.achados) == 1
    assert len(processos) == 2


def test_is_error_vira_resultado_com_erro():
    script = [(0, evento_resultado("deu ruim", is_error=True))]
    abrir, relogio, _ = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio)
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert resultado.erro == "deu ruim"


def test_timeout_por_agente_customizado():
    script = [(301, evento_resultado("[]"))]
    abrir, relogio, processos = fabrica([script])
    uc = AgenteClaudeCode(abrir_processo=abrir, relogio=relogio, timeout_primeiro_evento=400,
                          timeout_sem_evento=400, timeout_agente_padrao=300,
                          timeouts_por_agente={"qualidade": 600})
    resultado = uc.executar(AGENTE, WS, "sonnet", "usuario", lambda e: None)
    assert resultado.erro == ""  # usou os 600s do agente, não os 300 do padrão
