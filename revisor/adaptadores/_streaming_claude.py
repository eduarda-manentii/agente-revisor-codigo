"""Runner compartilhado de `claude -p --output-format stream-json`, usado tanto pelos agentes
especialistas (R3) quanto pelo coordenador (R4): timeout de primeiro evento, heartbeat, limite de
turnos e encerramento garantido do grupo de processo (R5). Não sabe nada de "agente" nem de
"coordenador" — só executa um processo e devolve o texto final ou um erro."""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
from typing import Callable

from revisor.portas import EventoAgente

# Se ANTHROPIC_API_KEY estiver no ambiente, o Claude Code cobra pela API em vez da assinatura.
VARIAVEIS_REMOVIDAS = ("ANTHROPIC_API_KEY",)


def montar_argumentos(
    executavel: str, modelo: str, arquivo_sistema: str, diretorio: str, tools: str = "Read,Grep,Glob",
) -> list[str]:
    """Função pura: monta a lista de argumentos do `claude -p`, sem executar nada. Testável sozinha."""
    return [
        executavel, "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--restricted",
        "--tools", tools,
        "--add-dir", diretorio,
        "--system-prompt-file", arquivo_sistema,
        "--model", modelo,
    ]


def _descrever_evento_ferramenta(bloco: dict) -> str:
    nome = bloco.get("name", "") or "?"
    entrada = bloco.get("input") or {}
    if nome == "Read":
        return f"Lendo {entrada.get('file_path', '?')}"
    if nome == "Grep":
        return f"Buscando '{entrada.get('pattern', '?')}'"
    if nome == "Glob":
        return f"Procurando {entrada.get('pattern', '?')}"
    return f"Usando {nome}"


class ProcessoReal:
    """Embrulha subprocess.Popen com leitura não bloqueante (thread + fila), pra dar timeout de
    verdade sem depender de select (que não funciona com pipes no Windows)."""

    def __init__(self, comando: list[str], cwd: str, env: dict, entrada: str) -> None:
        self._processo = subprocess.Popen(
            comando, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        try:
            self._processo.stdin.write(entrada)
            self._processo.stdin.close()
        except (BrokenPipeError, ValueError):
            pass
        self._fila: queue.Queue = queue.Queue()
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self) -> None:
        try:
            for linha in self._processo.stdout:
                self._fila.put(linha)
        finally:
            self._fila.put(None)

    def proxima_linha(self, timeout: float) -> str | None:
        try:
            return self._fila.get(timeout=max(0.0, timeout))
        except queue.Empty:
            raise TimeoutError from None

    def stderr(self) -> str:
        try:
            return self._processo.stderr.read() or ""
        except Exception:
            return ""

    def encerrar(self) -> None:
        """Sinal de término no grupo de processo inteiro e, após 5s, força (R5: sem órfãos)."""
        if self._processo.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self._processo.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self._processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._processo.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


def abrir_processo_real(comando: list[str], cwd: str, entrada: str) -> ProcessoReal:
    ambiente = {k: v for k, v in os.environ.items() if k not in VARIAVEIS_REMOVIDAS}
    return ProcessoReal(comando, cwd, ambiente, entrada)


def executar_streaming(
    abrir_processo: Callable[[list[str], str, str], object],
    comando: list[str],
    cwd: str,
    prompt: str,
    ao_progresso: Callable[[EventoAgente], None],
    *,
    limite_turnos: int,
    timeout_primeiro_evento: float,
    timeout_sem_evento: float,
    timeout_total: float,
    relogio: Callable[[], float],
) -> tuple[str | None, str | None]:
    """Roda um processo via `abrir_processo` e lê o stream até `result` ou um timeout/limite
    estourar. Devolve (texto_do_result, None) em sucesso, ou (None, mensagem_de_erro)."""
    processo = abrir_processo(comando, cwd, prompt)
    inicio = relogio()
    ultimo_evento = inicio
    chegou_primeiro = False
    turnos = 0
    resultado_final: dict | None = None

    while True:
        agora = relogio()
        limite_heartbeat = timeout_primeiro_evento if not chegou_primeiro else timeout_sem_evento
        falta_heartbeat = limite_heartbeat - (agora - ultimo_evento)
        falta_total = timeout_total - (agora - inicio)
        if falta_total <= 0:
            processo.encerrar()
            return None, "Tempo esgotado."
        if falta_heartbeat <= 0:
            processo.encerrar()
            return None, ("O processo não iniciou a tempo." if not chegou_primeiro
                         else "O processo ficou sem resposta.")
        try:
            linha = processo.proxima_linha(timeout=min(falta_heartbeat, falta_total))
        except TimeoutError:
            continue
        if linha is None:
            break
        chegou_primeiro = True
        ultimo_evento = relogio()
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            continue
        tipo = evento.get("type")
        if tipo == "assistant":
            for bloco in evento.get("message", {}).get("content", []):
                if bloco.get("type") == "tool_use":
                    turnos += 1
                    if turnos > limite_turnos:
                        processo.encerrar()
                        return None, "Limite de turnos excedido."
                    ao_progresso(EventoAgente("tool_use", _descrever_evento_ferramenta(bloco)))
        elif tipo == "result":
            resultado_final = evento
            break

    if resultado_final is None:
        return None, "O processo encerrou sem resultado."
    if resultado_final.get("is_error"):
        detalhe = str(resultado_final.get("result") or processo.stderr() or "erro desconhecido")[:500]
        return None, detalhe
    texto = resultado_final.get("result")
    if not isinstance(texto, str):
        return None, "Resposta sem o campo 'result'."
    ao_progresso(EventoAgente("resultado", "Concluído"))
    return texto, None
