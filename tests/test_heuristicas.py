import pytest

from revisor.dominio.apontamento import Severidade
from revisor.dominio.heuristicas import e_ruido, parse_saida_llm, selecionar_exemplos
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


def test_parse_saida_aceita_cerca_markdown_e_descarta_itens_invalidos():
    texto = """Segue:
```json
[{"arquivo": "A.java", "linha": 3, "severidade": "p1", "confianca": 15, "comentario": "ok de verdade"},
 {"arquivo": "A.java", "linha": "x", "severidade": "P1", "confianca": 5, "comentario": "c"},
 {"arquivo": "A.java", "linha": 4, "severidade": "P9", "confianca": 5, "comentario": "c"},
 {"arquivo": "", "linha": 4, "severidade": "P2", "confianca": 5, "comentario": "c"}]
```"""
    validos, descartados = parse_saida_llm(texto)
    assert descartados == 3
    assert len(validos) == 1
    assert validos[0].severidade == Severidade.P1
    assert validos[0].confianca == 10  # limitado a 10


def test_parse_saida_sem_json_falha():
    with pytest.raises(ValueError):
        parse_saida_llm("Não encontrei problemas.")


def test_parse_lista_vazia():
    assert parse_saida_llm("[]") == ([], 0)


def test_parse_saida_aceita_item_sem_motivo_nem_fontes():
    texto = '[{"arquivo": "A.java", "linha": 3, "severidade": "P1", "confianca": 7, "comentario": "c"}]'
    validos, descartados = parse_saida_llm(texto)
    assert descartados == 0
    assert validos[0].motivo == "" and validos[0].fontes_comentarios == ()
    assert validos[0].fontes_padrao_guia == "" and validos[0].fontes_regra_perfil == ""


def test_parse_saida_aceita_ids_como_int_string_e_hash():
    texto = (
        '[{"arquivo": "A.java", "linha": 3, "severidade": "P1", "confianca": 7, "comentario": "c", '
        '"motivo": "explicação", '
        '"fontes": {"comentarios": [123, "456", "#789", "abc"], '
        '"padrao_guia": "Título do padrão", "regra_perfil": "trecho exato"}}]'
    )
    validos, descartados = parse_saida_llm(texto)
    assert descartados == 0
    assert validos[0].motivo == "explicação"
    assert validos[0].fontes_comentarios == (123, 456, 789)  # "abc" descartado
    assert validos[0].fontes_padrao_guia == "Título do padrão"
    assert validos[0].fontes_regra_perfil == "trecho exato"


def test_parse_url_mr_com_subgrupos():
    ref = parse_url_mr("https://GitLab.empresa.com/grupo/sub/projeto/-/merge_requests/42/diffs")
    assert (ref.host, ref.projeto, ref.iid) == ("gitlab.empresa.com", "grupo/sub/projeto", 42)


@pytest.mark.parametrize("url", ["", "gitlab.com/x/-/merge_requests/1", "https://gitlab.com/x/-/issues/1"])
def test_parse_url_mr_invalida(url):
    with pytest.raises(ValueError):
        parse_url_mr(url)
