from datetime import datetime, timezone

import pytest

from revisor.dominio.apontamento import TransicaoInvalida
from revisor.dominio.modelos import StatusExecucao
from revisor.dominio.progresso import (
    esta_travado,
    formatar_contagem,
    formatar_duracao,
    transicionar,
)


@pytest.mark.parametrize("segundos,esperado", [
    (0, "00:00"),
    (59, "00:59"),
    (60, "01:00"),
    (3599, "59:59"),
    (3600, "01:00:00"),
])
def test_formatar_duracao_casos_de_borda(segundos, esperado):
    assert formatar_duracao(segundos) == esperado


@pytest.mark.parametrize("atual,total,esperado", [
    (None, 0, ""),
    (0, 0, ""),
    (1, 1, "1 de 1"),
    (3, 12, "3 de 12"),
])
def test_formatar_contagem(atual, total, esperado):
    assert formatar_contagem(atual, total) == esperado


def test_esta_travado_nao_dispara_aos_59s_e_dispara_aos_60s():
    inicio = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    atualizado_em = inicio.isoformat(timespec="seconds")
    agora_59 = inicio.replace(second=59)
    agora_60 = inicio.replace(minute=1, second=0)
    assert esta_travado(atualizado_em, agora_59, limite_segundos=60) is False
    assert esta_travado(atualizado_em, agora_60, limite_segundos=60) is True


def test_esta_travado_sem_heartbeat_nao_dispara():
    assert esta_travado("", datetime.now(timezone.utc)) is False


@pytest.mark.parametrize("atual,novo", [
    (StatusExecucao.PENDENTE, StatusExecucao.PROCESSANDO),
    (StatusExecucao.PROCESSANDO, StatusExecucao.CONCLUIDA),
    (StatusExecucao.PROCESSANDO, StatusExecucao.ERRO),
    (StatusExecucao.PROCESSANDO, StatusExecucao.CANCELADA),
    (StatusExecucao.PENDENTE, StatusExecucao.CANCELADA),
])
def test_transicoes_validas(atual, novo):
    assert transicionar(atual, novo) == novo


def test_transicao_para_o_mesmo_estado_e_idempotente():
    assert transicionar(StatusExecucao.CANCELADA, StatusExecucao.CANCELADA) == StatusExecucao.CANCELADA


@pytest.mark.parametrize("atual,novo", [
    (StatusExecucao.CONCLUIDA, StatusExecucao.PROCESSANDO),
    (StatusExecucao.ERRO, StatusExecucao.PROCESSANDO),
    (StatusExecucao.CANCELADA, StatusExecucao.PROCESSANDO),
    (StatusExecucao.PENDENTE, StatusExecucao.CONCLUIDA),
])
def test_transicoes_invalidas_sao_rejeitadas(atual, novo):
    with pytest.raises(TransicaoInvalida):
        transicionar(atual, novo)
