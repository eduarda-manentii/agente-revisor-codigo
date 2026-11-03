"""Adaptador LLM que chama o Claude Code em modo não interativo (`claude -p`).

Usa o login do Claude Code na sua máquina (assinatura Pro/Max/Team), sem chave de API.
O consumo entra nos limites de uso da sua assinatura.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


class ErroClaudeCode(RuntimeError):
    pass


# Se ANTHROPIC_API_KEY estiver no ambiente, o Claude Code cobra pela API em vez da assinatura.
_VARIAVEIS_REMOVIDAS = ("ANTHROPIC_API_KEY",)


class LLMClaudeCode:
    def __init__(
        self,
        executavel: str = "claude",
        modelo: str = "",
        timeout_segundos: int = 900,
        executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        caminho = shutil.which(executavel)  # resolve claude.cmd no Windows
        if caminho is None:
            raise ErroClaudeCode(
                f"Comando '{executavel}' não encontrado. Instale o Claude Code e rode 'claude' "
                "uma vez no terminal para fazer login."
            )
        self._executavel = caminho
        self._modelo = modelo
        self._timeout = timeout_segundos
        self._executar = executar

    def completar(self, sistema: str, usuario: str) -> str:
        with tempfile.TemporaryDirectory(prefix="revisor-") as pasta:
            # Pasta vazia como diretório de trabalho: não há código local para o Claude ler,
            # e nenhum CLAUDE.md ou .mcp.json de projeto é carregado.
            arquivo_sistema = Path(pasta) / "sistema.md"
            arquivo_sistema.write_text(sistema, encoding="utf-8")
            comando = [
                self._executavel, "-p",
                "--output-format", "json",
                "--tools", "",  # sem ferramentas: só texto entra, só texto sai
                "--system-prompt-file", str(arquivo_sistema),
            ]
            if self._modelo:
                comando += ["--model", self._modelo]
            ambiente = {k: v for k, v in os.environ.items() if k not in _VARIAVEIS_REMOVIDAS}
            try:
                processo = self._executar(
                    comando, input=usuario, capture_output=True, text=True, encoding="utf-8",
                    cwd=pasta, env=ambiente, timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as erro:
                raise ErroClaudeCode(f"O Claude Code não respondeu em {self._timeout}s.") from erro
        return self._interpretar(processo)

    @staticmethod
    def _interpretar(processo: subprocess.CompletedProcess) -> str:
        try:
            dados = json.loads(processo.stdout)
        except (json.JSONDecodeError, TypeError):
            detalhe = (processo.stderr or processo.stdout or "sem saída").strip()[:500]
            raise ErroClaudeCode(f"Claude Code falhou (código {processo.returncode}): {detalhe}")
        if processo.returncode != 0 or dados.get("is_error"):
            detalhe = str(dados.get("result") or processo.stderr or "erro desconhecido")[:500]
            raise ErroClaudeCode(f"Claude Code falhou: {detalhe}")
        resultado = dados.get("result")
        if not isinstance(resultado, str):
            raise ErroClaudeCode("Resposta do Claude Code sem o campo 'result'.")
        return resultado
