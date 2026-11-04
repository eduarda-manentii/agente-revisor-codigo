import json

import pytest

from revisor.dominio.agentes import Achado
from revisor.dominio.apontamento import Severidade
from revisor.dominio.consolidacao import GrupoAchados
from revisor.dominio.coordenador import aplicar_limite, interpretar_saida_coordenador


def achado(categoria="qualidade", confianca=8, comentario="problema", evidencia="trecho") -> Achado:
    return Achado(arquivo="A.java", linha=10, severidade=Severidade.P1, confianca=confianca,
                 categoria=categoria, comentario=comentario, evidencia=evidencia)


def grupo(*achados, linha=10) -> GrupoAchados:
    return GrupoAchados(arquivo="A.java", linha=linha, achados=tuple(achados))


def test_mapeia_apontamento_por_indice_de_grupo_e_traz_origens():
    grupos = [grupo(achado(categoria="qualidade"), achado(categoria="performance"))]
    saida = json.dumps({"apontamentos": [{"grupo": 1, "linha": 10, "severidade": "P0",
                                          "comentario": "Reescrito no tom do guia"}],
                        "descartados": [], "resumo": "ok"})
    resultado = interpretar_saida_coordenador(saida, grupos)
    assert len(resultado.apontamentos) == 1
    ap = resultado.apontamentos[0]
    assert ap.severidade == Severidade.P0
    assert ap.comentario == "Reescrito no tom do guia"
    assert set(ap.origens) == {"qualidade", "performance"}
    assert resultado.resumo == "ok"


def test_grupo_nao_mencionado_vira_descarte_automatico():
    grupos = [grupo(achado()), grupo(achado(), linha=50)]
    saida = json.dumps({"apontamentos": [{"grupo": 1, "severidade": "P1", "comentario": "x"}],
                        "descartados": []})
    resultado = interpretar_saida_coordenador(saida, grupos)
    assert len(resultado.apontamentos) == 1
    assert len(resultado.descartados) == 1
    assert resultado.descartados[0].motivo == "Não mencionado pelo coordenador."


def test_indice_duplicado_so_conta_na_primeira_vez():
    grupos = [grupo(achado())]
    saida = json.dumps({
        "apontamentos": [{"grupo": 1, "severidade": "P1", "comentario": "x"}],
        "descartados": [{"grupo": 1, "motivo": "duplicado, deveria ser ignorado"}],
    })
    resultado = interpretar_saida_coordenador(saida, grupos)
    assert len(resultado.apontamentos) == 1
    assert len(resultado.descartados) == 0


def test_indice_fora_do_intervalo_e_ignorado_mas_grupo_real_vira_descarte():
    grupos = [grupo(achado())]
    saida = json.dumps({"apontamentos": [{"grupo": 99, "severidade": "P1", "comentario": "x"}],
                        "descartados": []})
    resultado = interpretar_saida_coordenador(saida, grupos)
    assert resultado.apontamentos == ()
    assert len(resultado.descartados) == 1  # o grupo 1 de verdade, nunca citado


def test_json_sem_objeto_levanta_value_error():
    with pytest.raises(ValueError):
        interpretar_saida_coordenador("isso não é json nenhum", [grupo(achado())])


def test_conservacao_apontamentos_mais_descartados_igual_total_de_grupos():
    grupos = [grupo(achado(comentario=f"problema {i}"), linha=10 * i) for i in range(5)]
    saida = json.dumps({
        "apontamentos": [{"grupo": 1, "severidade": "P0", "comentario": "a"},
                         {"grupo": 3, "severidade": "P2", "comentario": "b"}],
        "descartados": [{"grupo": 2, "motivo": "especulação"}],
    })
    resultado = interpretar_saida_coordenador(saida, grupos)
    assert len(resultado.apontamentos) + len(resultado.descartados) == len(grupos)


def test_aplicar_limite_move_excedente_para_descartados_mantendo_maior_severidade_e_confianca():
    from revisor.dominio.coordenador import ApontamentoFinal
    apontamentos = (
        ApontamentoFinal("A.java", 1, Severidade.P2, 5, "baixo", ("qualidade",)),
        ApontamentoFinal("A.java", 2, Severidade.P0, 9, "alto", ("seguranca",)),
        ApontamentoFinal("A.java", 3, Severidade.P1, 7, "medio", ("testes",)),
    )
    from revisor.dominio.coordenador import ResultadoCoordenacao
    resultado = ResultadoCoordenacao(apontamentos=apontamentos)
    limitado = aplicar_limite(resultado, max_apontamentos=2)
    assert [a.comentario for a in limitado.apontamentos] == ["alto", "medio"]
    assert len(limitado.descartados) == 1
    assert limitado.descartados[0].comentario == "baixo"
    assert limitado.descartados[0].motivo == "Excedeu o limite de apontamentos do perfil."
