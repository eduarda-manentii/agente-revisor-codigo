"""Adaptador PortaAgente: roda um agente especialista como uma execução isolada de `claude -p`,
lendo a saída em streaming (R6) pra progresso/heartbeat e turnos, com timeouts e encerramento
garantido do grupo de processo (R5). Separado de `llm_claude_code.py`, que continua servindo só o
treino (chamada única, sem streaming nem ferramentas). A mecânica de processo é compartilhada com o
coordenador via `_streaming_claude.py`."""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from revisor.adaptadores._streaming_claude import (
    abrir_processo_real,
    executar_streaming,
    montar_argumentos,
)
from revisor.dominio.agentes import ResultadoAgente, parse_achados
from revisor.dominio.modelos import Agente
from revisor.portas import EventoAgente, Workspace

__all__ = ["AgenteClaudeCode", "ErroAgente", "montar_argumentos"]


class ErroAgente(RuntimeError):
    pass


class AgenteClaudeCode:
    def __init__(
        self,
        executavel: str = "claude",
        limite_turnos: int = 15,
        timeout_primeiro_evento: float = 60,
        timeout_sem_evento: float = 180,
        timeout_agente_padrao: float = 300,
        timeouts_por_agente: dict[str, float] | None = None,
        abrir_processo: Callable[[list[str], str, str], object] | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        caminho = shutil.which(executavel)
        if caminho is None:
            raise ErroAgente(f"Comando '{executavel}' não encontrado. Instale o Claude Code.")
        self._executavel = caminho
        self._limite_turnos = limite_turnos
        self._timeout_primeiro_evento = timeout_primeiro_evento
        self._timeout_sem_evento = timeout_sem_evento
        self._timeout_agente_padrao = timeout_agente_padrao
        self._timeouts_por_agente = timeouts_por_agente or {}
        self._abrir_processo = abrir_processo or abrir_processo_real
        self._relogio = relogio

    def _timeout_total(self, nome_agente: str) -> float:
        return self._timeouts_por_agente.get(nome_agente, self._timeout_agente_padrao)

    def executar(
        self, agente: Agente, workspace: Workspace, modelo: str, usuario: str,
        ao_progresso: Callable[[EventoAgente], None],
    ) -> ResultadoAgente:
        with tempfile.TemporaryDirectory(prefix="revisor-agente-") as pasta:
            arquivo_sistema = Path(pasta) / "sistema.md"
            arquivo_sistema.write_text(agente.instrucoes, encoding="utf-8")
            comando = montar_argumentos(
                self._executavel, modelo, str(arquivo_sistema), str(workspace.caminho)
            )
            prompt = usuario
            for tentativa in range(2):
                texto, erro = executar_streaming(
                    self._abrir_processo, comando, str(workspace.caminho), prompt, ao_progresso,
                    limite_turnos=self._limite_turnos,
                    timeout_primeiro_evento=self._timeout_primeiro_evento,
                    timeout_sem_evento=self._timeout_sem_evento,
                    timeout_total=self._timeout_total(agente.nome),
                    relogio=self._relogio,
                )
                if erro is not None:
                    return ResultadoAgente(agente=agente.nome, erro=erro, modelo_usado=modelo)
                try:
                    achados, descartados = parse_achados(texto, agente.nome)
                except ValueError as e:
                    if tentativa == 0:
                        prompt = (
                            f"{usuario}\n\n# Sua resposta anterior falhou: {e}\n"
                            "Responda só com o array JSON, sem texto antes ou depois."
                        )
                        continue
                    return ResultadoAgente(agente=agente.nome, erro=f"Saída inválida: {e}", modelo_usado=modelo)
                return ResultadoAgente(
                    agente=agente.nome, achados=tuple(achados), descartados=descartados, modelo_usado=modelo,
                )
