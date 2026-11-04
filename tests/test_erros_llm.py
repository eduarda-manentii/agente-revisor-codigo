import pytest

from revisor.dominio.erros_llm import TipoErroLLM, classificar_erro, deve_tentar_de_novo, proximo_modelo


@pytest.mark.parametrize("mensagem,esperado", [
    ("Error: overloaded_error", TipoErroLLM.SOBRECARGA),
    ("HTTP 503 Service Unavailable", TipoErroLLM.SOBRECARGA),
    ("rate limit exceeded", TipoErroLLM.SOBRECARGA),
    ("You have reached your usage limit", TipoErroLLM.LIMITE_USO),
    ("limite de uso atingido", TipoErroLLM.LIMITE_USO),
    ("Not logged in. Run claude to authenticate.", TipoErroLLM.NAO_AUTENTICADO),
    ("prompt too long for this model", TipoErroLLM.CONTEXTO_EXCEDIDO),
    ("algo totalmente inesperado aconteceu", TipoErroLLM.DESCONHECIDO),
])
def test_classificar_erro(mensagem, esperado):
    assert classificar_erro(mensagem) == esperado


@pytest.mark.parametrize("tipo,esperado", [
    (TipoErroLLM.SOBRECARGA, True),
    (TipoErroLLM.SAIDA_INVALIDA, True),
    (TipoErroLLM.LIMITE_USO, False),
    (TipoErroLLM.NAO_AUTENTICADO, False),
    (TipoErroLLM.CONTEXTO_EXCEDIDO, False),
    (TipoErroLLM.CANCELADO, False),
    (TipoErroLLM.DESCONHECIDO, False),
])
def test_deve_tentar_de_novo(tipo, esperado):
    assert deve_tentar_de_novo(tipo) is esperado


def test_proximo_modelo_so_depois_do_limite_de_falhas():
    cadeia = {"opus": "sonnet", "sonnet": "haiku"}
    assert proximo_modelo("opus", 1, cadeia) is None
    assert proximo_modelo("opus", 2, cadeia) == "sonnet"
    assert proximo_modelo("sonnet", 2, cadeia) == "haiku"
    assert proximo_modelo("haiku", 2, cadeia) is None  # fim da cadeia
