"""Apontamento de review e sua máquina de estados."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from revisor.dominio.fontes import Fontes


class Severidade(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class Status(StrEnum):
    PENDENTE = "PENDENTE"
    APROVADO = "APROVADO"
    REJEITADO = "REJEITADO"
    PUBLICADO = "PUBLICADO"
    FALHA_PUBLICACAO = "FALHA_PUBLICACAO"
    DESATUALIZADO = "DESATUALIZADO"


class MotivoRejeicao(StrEnum):
    FALSO_POSITIVO = "FALSO_POSITIVO"
    IRRELEVANTE = "IRRELEVANTE"
    JA_COBERTO = "JA_COBERTO"
    TOM = "TOM"
    OUTRO = "OUTRO"


class TransicaoInvalida(Exception):
    pass


_PUBLICAVEIS = frozenset({Status.APROVADO, Status.FALHA_PUBLICACAO})


@dataclass
class Apontamento:
    revisao_id: int
    arquivo: str
    caminho_antigo: str
    linha: int
    linha_antiga: int | None  # só em linha de contexto: o GitLab exige old_line + new_line
    severidade: Severidade
    confianca: int
    texto_original: str
    trecho: str
    texto_final: str = ""
    status: Status = Status.PENDENTE
    motivo_rejeicao: MotivoRejeicao | None = None
    discussion_id: str | None = None
    erro: str | None = None
    motivo: str = ""
    fontes: Fontes | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.texto_final:
            self.texto_final = self.texto_original

    def _exigir(self, permitidos: frozenset[Status], acao: str) -> None:
        if self.status not in permitidos:
            raise TransicaoInvalida(f"Não é possível {acao} um apontamento {self.status}.")

    def aprovar(self, texto_editado: str | None = None) -> None:
        self._exigir(frozenset({Status.PENDENTE, Status.APROVADO}), "aprovar")
        texto = (texto_editado if texto_editado is not None else self.texto_final).strip()
        if not texto:
            raise TransicaoInvalida("O comentário não pode ficar vazio.")
        self.texto_final = texto
        self.motivo_rejeicao = None
        self.status = Status.APROVADO

    def rejeitar(self, motivo: MotivoRejeicao) -> None:
        self._exigir(frozenset({Status.PENDENTE, Status.APROVADO}), "rejeitar")
        self.motivo_rejeicao = motivo
        self.status = Status.REJEITADO

    def reabrir(self) -> None:
        self._exigir(frozenset({Status.APROVADO, Status.REJEITADO}), "reabrir")
        self.motivo_rejeicao = None
        self.status = Status.PENDENTE

    @property
    def pode_publicar(self) -> bool:
        return self.status in _PUBLICAVEIS and self.discussion_id is None

    def marcar_publicado(self, discussion_id: str) -> None:
        self._exigir(_PUBLICAVEIS, "publicar")
        self.discussion_id = discussion_id
        self.erro = None
        self.status = Status.PUBLICADO

    def marcar_falha(self, erro: str) -> None:
        self._exigir(_PUBLICAVEIS, "marcar falha em")
        self.erro = erro
        self.status = Status.FALHA_PUBLICACAO

    def marcar_desatualizado(self) -> None:
        self._exigir(_PUBLICAVEIS, "marcar como desatualizado")
        self.status = Status.DESATUALIZADO
