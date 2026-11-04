"""Testa o adaptador do coordenador com processo falso — mesma mecânica de streaming dos agentes
(já validada em test_agente_claude_code.py), aqui só confirmando a integração específica dele:
texto bruto devolvido em sucesso, exceção em erro, sem retry (quem decide isso é RevisarMR)."""
import json

import pytest

from revisor.adaptadores import coordenador_claude_code
from revisor.adaptadores.coordenador_claude_code import CoordenadorClaudeCode, ErroCoordenador
from revisor.portas import Workspace


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
    def __init__(self, eventos: list, relogio: RelogioFalso) -> None:
        self._eventos = list(eventos)
        self._relogio = relogio

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
        pass


@pytest.fixture(autouse=True)
def claude_instalado(monkeypatch):
    monkeypatch.setattr(coordenador_claude_code.shutil, "which", lambda exe: f"/usr/bin/{exe}")


def fabrica(script):
    relogio = RelogioFalso()

    def abrir(comando, cwd, entrada):
        return ProcessoFalso(script, relogio)

    return abrir, relogio


WS = Workspace(caminho="/fake/ws", repo_cache="/fake/cache")


def test_claude_nao_instalado(monkeypatch):
    monkeypatch.setattr(coordenador_claude_code.shutil, "which", lambda exe: None)
    with pytest.raises(ErroCoordenador, match="não encontrado"):
        CoordenadorClaudeCode()


def test_devolve_texto_bruto_em_sucesso():
    abrir, relogio = fabrica([(0, evento_resultado('{"apontamentos": []}'))])
    uc = CoordenadorClaudeCode(abrir_processo=abrir, relogio=relogio)
    texto = uc.executar(WS, "sonnet", "sistema", "usuario", lambda e: None)
    assert texto == '{"apontamentos": []}'


def test_erro_vira_excecao():
    abrir, relogio = fabrica([(0, evento_resultado("deu ruim", is_error=True))])
    uc = CoordenadorClaudeCode(abrir_processo=abrir, relogio=relogio)
    with pytest.raises(ErroCoordenador, match="deu ruim"):
        uc.executar(WS, "sonnet", "sistema", "usuario", lambda e: None)


def test_timeout_total_customizado():
    abrir, relogio = fabrica([(601, evento_resultado("[]"))])
    uc = CoordenadorClaudeCode(abrir_processo=abrir, relogio=relogio, timeout_primeiro_evento=700,
                               timeout_sem_evento=700, timeout_total=600)
    with pytest.raises(ErroCoordenador, match="esgotado"):
        uc.executar(WS, "sonnet", "sistema", "usuario", lambda e: None)
