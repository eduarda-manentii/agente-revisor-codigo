"""Caso de uso: treinar um perfil.

"Treinar" = (1) descobrir os projetos (grupos + avulsos), (2) coletar, de forma incremental, os
comentários inline de toda a equipe nos MRs mergeados, (3) incorporar ao guia geral e aos guias de
microserviço os comentários que ainda não foram incorporados em cada camada, e (4) ler o código de
cada microserviço para manter um mapa técnico atualizado.

O conhecimento é sempre AGREGADO:
- comentários nunca são apagados (deduplicados por nota do GitLab);
- cada lote de comentários novos é fundido ao guia atual daquela camada, gerando uma nova versão;
- versões anteriores do guia ficam guardadas;
- se o treino cair no meio, os lotes já incorporados ficam salvos e o resto entra no próximo.
Nenhum modelo é ajustado (fine-tuning).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable

from revisor import prompts
from revisor.dominio.heuristicas import e_ruido
from revisor.dominio.mapa import excluido as caminho_excluido
from revisor.dominio.mapa import selecionar_arquivos_mapa
from revisor.dominio.modelos import GERAL, Exemplo, MapaProjeto, Perfil, StatusExecucao, Treino
from revisor.portas import PortaGitLab, PortaLLM, Repositorio

log = logging.getLogger(__name__)

_LIMITE_ARQUIVO_MAPA = 15_000
_LIMITE_AMOSTRA_MAPA = 150_000
_LIMITE_PASTAS_MAPA = 400


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TreinarPerfil:
    def __init__(
        self,
        gitlab: PortaGitLab,
        llm: PortaLLM,
        repo: Repositorio,
        perfis: dict[str, Perfil],
        grupos: list[str],
        projetos_avulsos: list[str],
        excluir_autores: set[str],
        desde_inicial: str,
        max_caracteres_lote: int = 120_000,
        min_comentarios_guia_micro: int = 30,
        mapa_validade_dias: int = 30,
        relogio: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._gitlab = gitlab
        self._llm = llm
        self._repo = repo
        self._perfis = perfis
        self._grupos = grupos
        self._projetos_avulsos = projetos_avulsos
        self._excluir = excluir_autores
        self._desde_inicial = desde_inicial
        self._max_lote = max_caracteres_lote
        self._min_comentarios_guia_micro = min_comentarios_guia_micro
        self._mapa_validade_dias = mapa_validade_dias
        self._relogio = relogio

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
            projetos = self._descobrir_projetos(treino)
            self._coletar(treino, projetos)
            self._incorporar(treino)
            self._mapear(treino, projetos)
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

    # ---------- descoberta (R1) ----------
    def _descobrir_projetos(self, treino: Treino) -> list[str]:
        self._progresso(treino, "Descobrindo projetos dos grupos…")
        projetos: list[str] = []
        for grupo in self._grupos:
            try:
                do_grupo = self._gitlab.listar_projetos(grupo)
            except Exception as erro:
                raise ValueError(f"Grupo '{grupo}' não encontrado ou sem permissão: {erro}") from erro
            for p in do_grupo:
                if p not in projetos:
                    projetos.append(p)
        for p in self._projetos_avulsos:
            if p not in projetos:
                projetos.append(p)
        if not projetos:
            raise ValueError("Nenhum projeto encontrado nos grupos configurados em GRUPOS_TREINO/PROJETOS_TREINO.")
        return projetos

    # ---------- coleta de comentários (R2) ----------
    def _coletar(self, treino: Treino, projetos: list[str]) -> None:
        perfil = self._perfis[treino.perfil]
        falhas = 0
        primeira_falha: Exception | None = None
        for projeto in projetos:
            try:
                # Checkpoint por projeto: incluir um projeto novo na configuração lê o histórico dele inteiro.
                checkpoint = None if treino.completo else self._repo.checkpoint(perfil.nome, projeto)
                desde = checkpoint or self._desde_inicial
                self._progresso(treino, f"Lendo comentários em {projeto} desde {desde[:10]}…")
                for c in self._gitlab.listar_comentarios(projeto, desde, self._excluir):
                    if not perfil.aceita(c.arquivo) or e_ruido(c.comentario):
                        continue
                    novo = self._repo.salvar_exemplo(
                        Exemplo(
                            perfil=perfil.nome, projeto=c.projeto, mr_iid=c.mr_iid, note_id=c.note_id,
                            arquivo=c.arquivo, linha=c.linha, trecho=c.trecho,
                            comentario=c.comentario, resolvido=c.resolvido,
                            autor=c.autor, criado_em=c.criado_em,
                        )
                    )
                    treino.novos_exemplos += int(novo)
                # Só avança depois de ler o projeto inteiro: se falhar no meio, relê na próxima vez.
                self._repo.salvar_checkpoint(perfil.nome, projeto, treino.iniciado_em)
            except Exception as erro:
                falhas += 1
                primeira_falha = primeira_falha or erro
                treino.avisos += f"{projeto}: {erro}\n"
                self._repo.salvar_treino(treino)
        if projetos and falhas == len(projetos):
            raise primeira_falha  # problema de configuração (ex.: token inválido): aborta o treino todo

    # ---------- incorporação aos guias (R3) ----------
    def _incorporar(self, treino: Treino) -> None:
        self._incorporar_geral(treino)
        self._incorporar_micro(treino)

    def _incorporar_geral(self, treino: Treino) -> None:
        exemplos = self._repo.listar_exemplos_pendentes(treino.perfil, GERAL)
        rejeitados = self._repo.listar_rejeitados_pendentes(treino.perfil)
        if not exemplos and not rejeitados:
            self._progresso(treino, "Nada novo para incorporar ao guia geral.")
            return

        lotes = prompts.dividir_em_lotes(exemplos, self._max_lote) or [[]]
        for numero, lote in enumerate(lotes, start=1):
            self._progresso(
                treino,
                f"Incorporando ao guia geral: lote {numero} de {len(lotes)} ({len(lote)} comentários)…",
            )
            guia_atual = self._repo.guia_ativo(treino.perfil, GERAL)
            rejeitados_do_lote = rejeitados if numero == 1 else []
            usuario = prompts.usuario_destilacao(
                guia_atual.conteudo if guia_atual else None, lote, rejeitados_do_lote
            )
            novo_guia = self._llm.completar(prompts.sistema_destilacao(GERAL), usuario).strip()
            if not novo_guia:
                raise ValueError("O modelo devolveu um guia vazio.")
            treino.guia_versao = self._repo.salvar_guia(
                treino.perfil,
                GERAL,
                novo_guia,
                note_ids=[e.note_id for e in lote],
                apontamento_ids=[a.id for a in rejeitados_do_lote if a.id is not None],
            )
        self._progresso(treino, f"Guia geral atualizado para a versão {treino.guia_versao}.")

    def _incorporar_micro(self, treino: Treino) -> None:
        for projeto, total in self._repo.contar_exemplos_por_projeto(treino.perfil):
            if total < self._min_comentarios_guia_micro:
                continue
            pendentes = self._repo.listar_exemplos_pendentes(treino.perfil, projeto)
            if not pendentes:
                continue
            lotes = prompts.dividir_em_lotes(pendentes, self._max_lote)
            for numero, lote in enumerate(lotes, start=1):
                self._progresso(
                    treino,
                    f"Incorporando ao guia de {projeto}: lote {numero} de {len(lotes)} "
                    f"({len(lote)} comentários)…",
                )
                guia_atual = self._repo.guia_ativo(treino.perfil, projeto)
                usuario = prompts.usuario_destilacao(
                    guia_atual.conteudo if guia_atual else None, lote, []
                )
                novo_guia = self._llm.completar(prompts.sistema_destilacao(projeto), usuario).strip()
                if not novo_guia:
                    raise ValueError(f"O modelo devolveu um guia vazio para {projeto}.")
                self._repo.salvar_guia(
                    treino.perfil, projeto, novo_guia,
                    note_ids=[e.note_id for e in lote], apontamento_ids=[],
                )

    # ---------- mapa técnico (R4) ----------
    def _mapear(self, treino: Treino, projetos: list[str]) -> None:
        perfil = self._perfis[treino.perfil]
        for projeto in projetos:
            try:
                self._mapear_projeto(treino, perfil, projeto)
            except Exception as erro:
                treino.avisos += f"{projeto}: não foi possível gerar o mapa técnico: {erro}\n"
                self._repo.salvar_treino(treino)

    def _mapear_projeto(self, treino: Treino, perfil: Perfil, projeto: str) -> None:
        existente = self._repo.mapa_ativo(projeto)
        if existente and not treino.completo:
            idade_dias = (self._relogio() - datetime.fromisoformat(existente.criado_em)).days
            if idade_dias < self._mapa_validade_dias:
                return

        arvore = self._gitlab.obter_arvore(projeto)
        if not any(perfil.aceita(c) for c in arvore.caminhos):
            return
        if existente and existente.sha == arvore.sha and not treino.completo:
            return

        self._progresso(treino, f"Lendo código de {projeto}…")
        arquivos: list[tuple[str, str]] = []
        total = 0
        for caminho in selecionar_arquivos_mapa(list(arvore.caminhos)):
            conteudo = self._gitlab.obter_arquivo(projeto, caminho, arvore.sha)
            if conteudo is None:
                continue
            conteudo = conteudo[:_LIMITE_ARQUIVO_MAPA]
            if total + len(conteudo) > _LIMITE_AMOSTRA_MAPA:
                break
            arquivos.append((caminho, conteudo))
            total += len(conteudo)

        pastas = sorted(
            {
                str(PurePosixPath(c).parent) for c in arvore.caminhos
                if PurePosixPath(c).parent != PurePosixPath(".") and not caminho_excluido(c)
            }
        )[:_LIMITE_PASTAS_MAPA]

        usuario = prompts.usuario_mapa(projeto, arquivos, pastas)
        conteudo_mapa = self._llm.completar(prompts.sistema_mapa(), usuario).strip()
        self._repo.salvar_mapa(
            MapaProjeto(
                projeto=projeto, sha=arvore.sha, conteudo=conteudo_mapa,
                arquivos_lidos=tuple(c for c, _ in arquivos),
                criado_em=self._relogio().isoformat(timespec="seconds"),
            )
        )
