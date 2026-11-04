"""Adaptador PortaCoordenador: roda o coordenador como uma execução isolada de `claude -p`, com
leitura do workspace (R4.2) — mesma mecânica de streaming dos agentes (R3), via
`_streaming_claude.py`. Não decide se o JSON de saída é válido: devolve o texto bruto; quem chama
(`RevisarMR`) tenta o parse (`dominio/coordenador.py`) e decide se tenta de novo."""
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
from revisor.portas import EventoAgente, Workspace


class ErroCoordenador(RuntimeError):
    pass


class CoordenadorClaudeCode:
    def __init__(
        self,
        executavel: str = "claude",
        limite_turnos: int = 30,
        timeout_primeiro_evento: float = 60,
        timeout_sem_evento: float = 180,
        timeout_total: float = 600,
        abrir_processo: Callable[[list[str], str, str], object] | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        caminho = shutil.which(executavel)
        if caminho is None:
            raise ErroCoordenador(f"Comando '{executavel}' não encontrado. Instale o Claude Code.")
        self._executavel = caminho
        self._limite_turnos = limite_turnos
        self._timeout_primeiro_evento = timeout_primeiro_evento
        self._timeout_sem_evento = timeout_sem_evento
        self._timeout_total = timeout_total
        self._abrir_processo = abrir_processo or abrir_processo_real
        self._relogio = relogio

    def executar(
        self, workspace: Workspace, modelo: str, sistema: str, usuario: str,
        ao_progresso: Callable[[EventoAgente], None],
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="revisor-coordenador-") as pasta:
            arquivo_sistema = Path(pasta) / "sistema.md"
            arquivo_sistema.write_text(sistema, encoding="utf-8")
            comando = montar_argumentos(
                self._executavel, modelo, str(arquivo_sistema), str(workspace.caminho)
            )
            texto, erro = executar_streaming(
                self._abrir_processo, comando, str(workspace.caminho), usuario, ao_progresso,
                limite_turnos=self._limite_turnos,
                timeout_primeiro_evento=self._timeout_primeiro_evento,
                timeout_sem_evento=self._timeout_sem_evento,
                timeout_total=self._timeout_total,
                relogio=self._relogio,
            )
            if erro is not None:
                raise ErroCoordenador(erro)
            return texto
