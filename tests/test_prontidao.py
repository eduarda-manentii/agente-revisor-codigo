import pytest

from revisor.dominio.apontamento import Apontamento, Severidade, Status
from revisor.dominio.prontidao import calcular_prontidao, comparar_com_anterior


def ap(arquivo="A.java", linha=1, severidade=Severidade.P1, status=Status.PENDENTE,
       texto="Mesmo problema de sempre") -> Apontamento:
    a = Apontamento(1, arquivo, arquivo, linha, None, severidade, 8, texto, "trecho")
    a.status = status
    return a


def test_sem_apontamentos_e_100_por_cento_pronto():
    assert calcular_prontidao([]) == 100


@pytest.mark.parametrize("severidade,esperado", [
    (Severidade.P0, 75),
    (Severidade.P1, 90),
    (Severidade.P2, 97),
])
def test_cada_severidade_pesa_diferente(severidade, esperado):
    assert calcular_prontidao([ap(severidade=severidade)]) == esperado


def test_rejeitado_e_desatualizado_nao_contam_contra_a_prontidao():
    apontamentos = [
        ap(severidade=Severidade.P0, status=Status.REJEITADO),
        ap(severidade=Severidade.P0, status=Status.DESATUALIZADO),
    ]
    assert calcular_prontidao(apontamentos) == 100


def test_prontidao_nao_fica_negativa():
    apontamentos = [ap(linha=i, severidade=Severidade.P0) for i in range(10)]
    assert calcular_prontidao(apontamentos) == 0


def test_aprovado_e_publicado_continuam_contando():
    apontamentos = [ap(severidade=Severidade.P1, status=Status.APROVADO),
                    ap(linha=2, severidade=Severidade.P1, status=Status.PUBLICADO)]
    assert calcular_prontidao(apontamentos) == 80


def test_comparar_com_anterior_classifica_resolvido_repetido_e_novo():
    anteriores = [
        ap(arquivo="A.java", linha=1, texto="Problema A"),  # some agora -> resolvido
        ap(arquivo="B.java", linha=2, texto="Problema B"),  # continua -> repetido
    ]
    atuais = [
        ap(arquivo="B.java", linha=2, texto="Problema B"),
        ap(arquivo="C.java", linha=3, texto="Problema C"),  # novo
    ]
    comparacao = comparar_com_anterior(atuais, anteriores)
    assert comparacao.resolvidos == 1
    assert comparacao.repetidos == 1
    assert comparacao.novos == 1


def test_comparacao_ignora_diferenca_de_maiusculas_e_espacos():
    anteriores = [ap(texto="  Mass   ASSIGNMENT no setStatus ")]
    atuais = [ap(texto="mass assignment no setstatus")]
    comparacao = comparar_com_anterior(atuais, anteriores)
    assert comparacao == comparar_com_anterior(atuais, atuais)  # repetido, não "novo" nem "resolvido"
    assert comparacao.repetidos == 1 and comparacao.resolvidos == 0 and comparacao.novos == 0


def test_comparacao_sem_revisao_anterior_e_tudo_novo():
    atuais = [ap(), ap(linha=2)]
    comparacao = comparar_com_anterior(atuais, [])
    assert comparacao.novos == 2 and comparacao.resolvidos == 0 and comparacao.repetidos == 0
