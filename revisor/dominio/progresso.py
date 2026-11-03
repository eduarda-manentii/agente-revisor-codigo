"""Funções puras de progresso/tempo de uma revisão: duração, contagem, inatividade e máquina
de estados. Nada aqui lê o relógio real nem o banco — tudo recebe o que precisa por parâmetro,
para dar de testar com um relógio fixo."""
from __future__ import annotations

from datetime import datetime, timezone

from revisor.dominio.apontamento import TransicaoInvalida
from revisor.dominio.modelos import StatusExecucao


class RevisaoCancelada(Exception):
    """Levantada internamente quando o usuário cancela uma revisão em andamento."""


def formatar_duracao(segundos: int) -> str:
    """mm:ss abaixo de 1h, hh:mm:ss a partir de 3600s."""
    segundos = max(0, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas:02d}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


def formatar_contagem(atual: int | None, total: int | None) -> str:
    """"X de Y", ou vazio quando não há itens contáveis (lista vazia ou não informado)."""
    if not atual or not total:
        return ""
    return f"{atual} de {total}"


def esta_travado(atualizado_em: str, agora: datetime, limite_segundos: int = 60) -> bool:
    """True se não há heartbeat (`atualizado_em`) há pelo menos `limite_segundos`."""
    if not atualizado_em:
        return False
    ultima = datetime.fromisoformat(atualizado_em)
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)
    return (agora - ultima).total_seconds() >= limite_segundos


_TRANSICOES: dict[StatusExecucao, frozenset[StatusExecucao]] = {
    StatusExecucao.PENDENTE: frozenset({StatusExecucao.PROCESSANDO, StatusExecucao.CANCELADA}),
    StatusExecucao.PROCESSANDO: frozenset(
        {StatusExecucao.CONCLUIDA, StatusExecucao.ERRO, StatusExecucao.CANCELADA}
    ),
    StatusExecucao.CONCLUIDA: frozenset(),
    StatusExecucao.ERRO: frozenset(),
    StatusExecucao.CANCELADA: frozenset(),
}


def transicionar(atual: StatusExecucao, novo: StatusExecucao) -> StatusExecucao:
    """Valida a máquina de estados da execução: pendente -> processando -> concluída/erro/cancelada.

    Chamar com o mesmo estado (ex.: cancelar duas vezes) é idempotente."""
    if novo == atual:
        return atual
    if novo not in _TRANSICOES.get(atual, frozenset()):
        raise TransicaoInvalida(f"Não é possível ir de {atual} para {novo}.")
    return novo
