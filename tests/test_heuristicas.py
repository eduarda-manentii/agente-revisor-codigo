import pytest

from revisor.dominio.heuristicas import e_ruido, selecionar_exemplos
from revisor.dominio.modelos import Exemplo, parse_url_mr


@pytest.mark.parametrize("texto", ["lgtm", "LGTM!", "👍", "ok", "curto demais", "  valeu.  "])
def test_ruido(texto):
    assert e_ruido(texto)


def test_comentario_real_nao_e_ruido():
    assert not e_ruido("Esse status vem do request, deveria vir do contexto.")


def ex(trecho: str, resolvido: bool = False, note_id: int = 1, projeto: str = "p") -> Exemplo:
    return Exemplo("back", projeto, 1, note_id, "A.java", 1, trecho, "comentário", resolvido)


def test_selecao_por_similaridade_e_desempate_por_acolhimento():
    alvo = "contrato.setStatus(request.getStatus())"
    parecido_nao_acolhido = ex("pedido.setStatus(request.getStatus())", False, 1)
    parecido_acolhido = ex("pedido.setStatus(request.getStatus())", True, 2)
    sem_relacao = ex("logger.info(mensagem)", True, 3)
    escolhidos = selecionar_exemplos(alvo, [parecido_nao_acolhido, sem_relacao, parecido_acolhido], k=5)
    assert escolhidos == [parecido_acolhido, parecido_nao_acolhido]


def test_selecao_respeita_k_e_alvo_vazio():
    exemplos = [ex("setStatus getStatus", note_id=i) for i in range(5)]
    assert len(selecionar_exemplos("setStatus", exemplos, k=2)) == 2
    assert selecionar_exemplos("", exemplos, k=2) == []


def test_exemplo_do_mesmo_projeto_ganha_de_outro_com_mesma_similaridade():
    alvo = "contrato.setStatus(request.getStatus())"
    do_mr = ex("pedido.setStatus(request.getStatus())", note_id=1, projeto="g/divida")
    de_outro = ex("pedido.setStatus(request.getStatus())", note_id=2, projeto="g/cobranca")
    escolhidos = selecionar_exemplos(alvo, [de_outro, do_mr], k=5, projeto_mr="g/divida")
    assert escolhidos == [do_mr, de_outro]


def test_bonus_de_projeto_nao_traz_exemplo_sem_similaridade_nenhuma():
    sem_relacao = ex("logger.info(mensagem)", note_id=1, projeto="g/divida")
    assert selecionar_exemplos("setStatus", [sem_relacao], k=5, projeto_mr="g/divida") == []


def test_parse_url_mr_com_subgrupos():
    ref = parse_url_mr("https://GitLab.empresa.com/grupo/sub/projeto/-/merge_requests/42/diffs")
    assert (ref.host, ref.projeto, ref.iid) == ("gitlab.empresa.com", "grupo/sub/projeto", 42)


@pytest.mark.parametrize("url", ["", "gitlab.com/x/-/merge_requests/1", "https://gitlab.com/x/-/issues/1"])
def test_parse_url_mr_invalida(url):
    with pytest.raises(ValueError):
        parse_url_mr(url)
