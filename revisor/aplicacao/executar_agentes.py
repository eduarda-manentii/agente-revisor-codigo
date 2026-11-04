"""Caso de uso novo (v3 R3/R5/R6): roda os agentes especialistas do nível de risco escolhido, em
paralelo, com disjuntor de modelo e progresso persistido. Ainda não é chamado pelo fluxo de review
atual — isso entra quando o coordenador (R4) substituir a chamada única."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from revisor import prompts
from revisor.dominio.agentes import EstadoAgente, ResultadoAgente
from revisor.dominio.erros_llm import TipoErroLLM, classificar_erro, proximo_modelo
from revisor.dominio.heuristicas import selecionar_exemplos
from revisor.dominio.modelos import Agente, ExecucaoAgente, Exemplo, Guia, Perfil
from revisor.portas import EventoAgente, PortaAgente, Repositorio, Workspace

_MODELO_RESERVA_PADRAO = {"opus": "sonnet", "sonnet": "haiku"}
_EXEMPLOS_POR_AGENTE = 8


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _estado_do_erro(mensagem: str) -> EstadoAgente:
    minuscula = mensagem.lower()
    if "não iniciou" in minuscula or "sem resposta" in minuscula:
        return EstadoAgente.SEM_RESPOSTA
    if "esgotado" in minuscula:
        return EstadoAgente.ENCERRADO_POR_TEMPO
    return EstadoAgente.FALHOU


class ExecutarAgentes:
    def __init__(
        self,
        porta_agente: PortaAgente,
        repo: Repositorio,
        agentes: dict[str, Agente],
        agentes_paralelos: int = 2,
        modelo_reserva: dict[str, str] | None = None,
        limite_falhas_sobrecarga: int = 2,
    ) -> None:
        self._agente_porta = porta_agente
        self._repo = repo
        self._agentes = agentes
        self._paralelos = max(1, agentes_paralelos)
        self._modelo_reserva = modelo_reserva or _MODELO_RESERVA_PADRAO
        self._limite_falhas = limite_falhas_sobrecarga

    def rodar(
        self,
        revisao_id: int,
        perfil: Perfil,
        nivel_risco: str,
        workspace: Workspace,
        arquivos: list[str],
        exemplos: list[Exemplo] | None = None,
        guia_ativo: Guia | None = None,
        codigo_alvo: str = "",
    ) -> list[ResultadoAgente]:
        nomes = [n for n in perfil.agentes_do_nivel(nivel_risco) if n in self._agentes]
        if not nomes:
            return []
        exemplos = exemplos or []

        bloqueio = threading.Lock()
        falhas_sobrecarga = 0

        def tarefa(nome: str) -> ResultadoAgente:
            nonlocal falhas_sobrecarga
            agente = self._agentes[nome]
            with bloqueio:
                falhas_atuais = falhas_sobrecarga
            modelo_base = perfil.modelo_por_agente.get(nome, agente.modelo_padrao)
            modelo = proximo_modelo(modelo_base, falhas_atuais, self._modelo_reserva, self._limite_falhas)
            modelo = modelo or modelo_base

            usuario = prompts.usuario_agente(arquivos)
            if nome == "estilo-revisor":
                selecionados = selecionar_exemplos(codigo_alvo, exemplos, _EXEMPLOS_POR_AGENTE)
                usuario += "\n\n" + prompts.contexto_estilo_revisor(guia_ativo, selecionados)

            iniciado_em = _agora()
            self._registrar(revisao_id, nome, EstadoAgente.RODANDO, "Iniciando...", modelo, iniciado_em)

            def ao_progresso(evento: EventoAgente) -> None:
                self._registrar(revisao_id, nome, EstadoAgente.RODANDO, evento.descricao, modelo, iniciado_em)
                self._repo.registrar_evento(revisao_id, f"{nome}: {evento.descricao}", _agora())

            resultado = self._agente_porta.executar(agente, workspace, modelo, usuario, ao_progresso)

            if resultado.erro:
                if classificar_erro(resultado.erro) == TipoErroLLM.SOBRECARGA:
                    with bloqueio:
                        falhas_sobrecarga += 1
                self._registrar(revisao_id, nome, _estado_do_erro(resultado.erro), resultado.erro,
                                modelo, iniciado_em)
            else:
                self._registrar(revisao_id, nome, EstadoAgente.CONCLUIDO, "Concluído", modelo, iniciado_em)
            return resultado

        resultados: list[ResultadoAgente] = []
        with ThreadPoolExecutor(max_workers=self._paralelos) as executor:
            futuros = [executor.submit(tarefa, nome) for nome in nomes]
            for futuro in as_completed(futuros):
                resultados.append(futuro.result())
        return resultados

    def _registrar(
        self, revisao_id: int, agente: str, estado: EstadoAgente, etapa: str, modelo: str, iniciado_em: str,
    ) -> None:
        self._repo.salvar_execucao_agente(ExecucaoAgente(
            revisao_id=revisao_id, agente=agente, estado=estado.value, etapa=etapa, modelo=modelo,
            iniciado_em=iniciado_em, atualizado_em=_agora(),
        ))
