"""Casos de uso: triagem (aprovar/editar/rejeitar) e publicação no MR."""
from __future__ import annotations

from dataclasses import dataclass

from revisor.dominio.apontamento import MotivoRejeicao
from revisor.portas import PortaGitLab, Posicao, Repositorio


class TriarApontamento:
    def __init__(self, repo: Repositorio) -> None:
        self._repo = repo

    def aprovar(self, apontamento_id: int, texto: str | None = None) -> None:
        ap = self._repo.obter_apontamento(apontamento_id)
        ap.aprovar(texto)
        self._repo.salvar_apontamento(ap)

    def rejeitar(self, apontamento_id: int, motivo: MotivoRejeicao) -> None:
        ap = self._repo.obter_apontamento(apontamento_id)
        ap.rejeitar(motivo)
        self._repo.salvar_apontamento(ap)

    def reabrir(self, apontamento_id: int) -> None:
        ap = self._repo.obter_apontamento(apontamento_id)
        ap.reabrir()
        self._repo.salvar_apontamento(ap)


@dataclass(frozen=True)
class ResultadoPublicacao:
    publicados: int = 0
    falhas: int = 0
    desatualizados: int = 0


class PublicarAprovados:
    def __init__(self, gitlab: PortaGitLab, repo: Repositorio) -> None:
        self._gitlab = gitlab
        self._repo = repo

    def executar(self, revisao_id: int) -> ResultadoPublicacao:
        revisao = self._repo.obter_revisao(revisao_id)
        pendentes = [a for a in self._repo.listar_apontamentos(revisao_id) if a.pode_publicar]
        if not pendentes:
            return ResultadoPublicacao()

        # Se o MR recebeu commits depois do review, as linhas podem não bater mais.
        if self._gitlab.head_sha_atual(revisao.projeto, revisao.mr_iid) != revisao.head_sha:
            for ap in pendentes:
                ap.marcar_desatualizado()
                self._repo.salvar_apontamento(ap)
            return ResultadoPublicacao(desatualizados=len(pendentes))

        publicados = falhas = 0
        for ap in pendentes:
            posicao = Posicao(
                base_sha=revisao.base_sha,
                start_sha=revisao.start_sha,
                head_sha=revisao.head_sha,
                caminho_antigo=ap.caminho_antigo,
                caminho_novo=ap.arquivo,
                linha_nova=ap.linha,
                linha_antiga=ap.linha_antiga,
            )
            try:
                discussion_id = self._gitlab.criar_comentario(
                    revisao.projeto, revisao.mr_iid, posicao, ap.texto_final
                )
                ap.marcar_publicado(discussion_id)
                publicados += 1
            except Exception as erro:
                ap.marcar_falha(str(erro) or erro.__class__.__name__)
                falhas += 1
            # Salva um por um: se o processo cair no meio, o que já foi publicado não duplica.
            self._repo.salvar_apontamento(ap)
        return ResultadoPublicacao(publicados=publicados, falhas=falhas)
