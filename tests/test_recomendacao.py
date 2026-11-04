import pytest

from revisor.dominio.apontamento import Severidade
from revisor.dominio.recomendacao import Recomendacao, calcular_recomendacao


@pytest.mark.parametrize("severidades,esperado", [
    ([], Recomendacao.APROVAR),
    ([Severidade.P2], Recomendacao.APROVAR),
    ([Severidade.P2, Severidade.P2, Severidade.P2], Recomendacao.APROVAR),
    ([Severidade.P1], Recomendacao.APROVAR_COM_COMENTARIOS),
    ([Severidade.P1, Severidade.P1], Recomendacao.APROVAR_COM_COMENTARIOS),
    ([Severidade.P1, Severidade.P1, Severidade.P2], Recomendacao.APROVAR_COM_COMENTARIOS),
    ([Severidade.P1, Severidade.P1, Severidade.P1], Recomendacao.AJUSTES_NECESSARIOS),
    ([Severidade.P1] * 5, Recomendacao.AJUSTES_NECESSARIOS),
    ([Severidade.P0], Recomendacao.MUDANCAS_SIGNIFICATIVAS),
    ([Severidade.P0, Severidade.P1, Severidade.P1, Severidade.P1], Recomendacao.MUDANCAS_SIGNIFICATIVAS),
    ([Severidade.P0, Severidade.P2], Recomendacao.MUDANCAS_SIGNIFICATIVAS),
])
def test_tabela_de_recomendacao(severidades, esperado):
    assert calcular_recomendacao(severidades) == esperado
