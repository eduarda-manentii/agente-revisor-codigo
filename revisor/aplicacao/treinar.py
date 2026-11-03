"""Caso de uso: treinar um perfil.

"Treinar" = (1) coletar, de forma incremental, os comentários inline da pessoa-alvo nos MRs
mergeados e (2) incorporar ao guia de review os comentários que ainda não foram incorporados.

O conhecimento é sempre AGREGADO:
- comentários nunca são apagados (deduplicados por nota do GitLab);
- cada lote de comentários novos é fundido ao guia atual, gerando uma nova versão;
- versões anteriores do guia ficam guardadas;
- se o treino cair no meio, os lotes já incorporados ficam salvos e o resto entra no próximo.
Nenhum modelo é ajustado (fine-tuning).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from revisor import prompts
from revisor.dominio.heuristicas import e_ruido
from revisor.dominio.modelos import Exemplo, Perfil, StatusExecucao, Treino
from revisor.portas import PortaGitLab, PortaLLM, Repositorio

log = logging.getLogger(__name__)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TreinarPerfil:
    def __init__(
        self,
        gitlab: PortaGitLab,
        llm: PortaLLM,
        repo: Repositorio,
        perfis: dict[str, Perfil],
        revisor_alvo: str,
        projetos: list[str],
        desde_inicial: str,
        max_caracteres_lote: int = 120_000,
    ) -> None:
        self._gitlab = gitlab
        self._llm = llm
        self._repo = repo
        self._perfis = perfis
        self._alvo = revisor_alvo
        self._projetos = projetos
        self._desde_inicial = desde_inicial
        self._max_lote = max_caracteres_lote

    def iniciar(self, nome_perfil: str, completo: bool = False) -> int:
        """`completo=True` relê todo o histórico desde TREINO_DESDE (sem duplicar nada)."""
        if nome_perfil not in self._perfis:
            raise ValueError(f"Perfil desconhecido: {nome_perfil}")
        ultimo = self._repo.ultimo_treino(nome_perfil)
        if ultimo and ultimo.status == StatusExecucao.PROCESSANDO:
            raise ValueError(f"Já existe um treino do perfil {nome_perfil} em andamento.")
        return self._repo.criar_treino(Treino(perfil=nome_perfil, completo=completo, iniciado_em=_agora()))

    def executar(self, treino_id: int) -> None:
        treino = self._repo.obter_treino(treino_id)
        try:
            self._coletar(treino)
            self._incorporar(treino)
            treino.status = StatusExecucao.CONCLUIDA
        except Exception as erro:
            log.exception("Falha no treino %s", treino_id)
            treino.status = StatusExecucao.ERRO
            treino.erro = str(erro) or erro.__class__.__name__
        treino.concluido_em = _agora()
        self._repo.salvar_treino(treino)

    def _progresso(self, treino: Treino, texto: str) -> None:
        treino.progresso = texto
        self._repo.salvar_treino(treino)

    def _coletar(self, treino: Treino) -> None:
        perfil = self._perfis[treino.perfil]
        for projeto in self._projetos:
            # Checkpoint por projeto: incluir um projeto novo na configuração lê o histórico dele inteiro.
            checkpoint = None if treino.completo else self._repo.checkpoint(perfil.nome, projeto)
            desde = checkpoint or self._desde_inicial
            self._progresso(treino, f"Lendo comentários em {projeto} desde {desde[:10]}…")
            for c in self._gitlab.listar_comentarios(projeto, self._alvo, desde):
                if not perfil.aceita(c.arquivo) or e_ruido(c.comentario):
                    continue
                novo = self._repo.salvar_exemplo(
                    Exemplo(
                        perfil=perfil.nome, projeto=c.projeto, mr_iid=c.mr_iid, note_id=c.note_id,
                        arquivo=c.arquivo, linha=c.linha, trecho=c.trecho,
                        comentario=c.comentario, resolvido=c.resolvido,
                    )
                )
                treino.novos_exemplos += int(novo)
            # Só avança depois de ler o projeto inteiro: se falhar no meio, relê na próxima vez.
            self._repo.salvar_checkpoint(perfil.nome, projeto, treino.iniciado_em)

    def _incorporar(self, treino: Treino) -> None:
        exemplos = self._repo.listar_exemplos_pendentes(treino.perfil)
        rejeitados = self._repo.listar_rejeitados_pendentes(treino.perfil)
        if not exemplos and not rejeitados:
            treino.progresso = "Nada novo para incorporar: o guia atual já contém tudo."
            return

        lotes = prompts.dividir_em_lotes(exemplos, self._max_lote) or [[]]
        for numero, lote in enumerate(lotes, start=1):
            self._progresso(
                treino, f"Incorporando ao guia: lote {numero} de {len(lotes)} ({len(lote)} comentários)…"
            )
            guia_atual = self._repo.guia_ativo(treino.perfil)
            rejeitados_do_lote = rejeitados if numero == 1 else []
            usuario = prompts.usuario_destilacao(
                guia_atual.conteudo if guia_atual else None, lote, rejeitados_do_lote
            )
            novo_guia = self._llm.completar(prompts.sistema_destilacao(), usuario).strip()
            if not novo_guia:
                raise ValueError("O modelo devolveu um guia vazio.")
            # Salva versão + marca o lote como incorporado na mesma transação.
            treino.guia_versao = self._repo.salvar_guia(
                treino.perfil,
                novo_guia,
                note_ids=[e.note_id for e in lote],
                apontamento_ids=[a.id for a in rejeitados_do_lote if a.id is not None],
            )
        treino.progresso = f"Guia atualizado para a versão {treino.guia_versao}."
