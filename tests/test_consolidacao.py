from revisor.dominio.agentes import Achado
from revisor.dominio.apontamento import Severidade
from revisor.dominio.consolidacao import pre_consolidar


def achado(arquivo="A.java", linha=10, categoria="qualidade",
          comentario="Mass assignment sem validar o status do request", confianca=8) -> Achado:
    return Achado(arquivo=arquivo, linha=linha, severidade=Severidade.P1, confianca=confianca,
                 categoria=categoria, comentario=comentario, evidencia="trecho")


def test_mesmo_arquivo_distancia_3_e_mesmo_texto_agrupa():
    grupos = pre_consolidar([achado(linha=10), achado(linha=13, categoria="estilo-revisor")])
    assert len(grupos) == 1
    assert set(grupos[0].origens) == {"qualidade", "estilo-revisor"}


def test_mesmo_arquivo_distancia_4_nao_agrupa():
    grupos = pre_consolidar([achado(linha=10), achado(linha=14, categoria="estilo-revisor")])
    assert len(grupos) == 2


def test_arquivos_diferentes_nunca_agrupam_mesmo_com_texto_identico():
    grupos = pre_consolidar([achado(arquivo="A.java", linha=10), achado(arquivo="B.java", linha=10)])
    assert len(grupos) == 2


def test_mesmo_arquivo_perto_mas_problema_textualmente_distinto_nao_agrupa():
    a = achado(linha=10, comentario="N+1 nessa consulta dentro do laço")
    b = achado(linha=11, categoria="seguranca", comentario="Token de API exposto em texto plano")
    grupos = pre_consolidar([a, b])
    assert len(grupos) == 2


def test_conservacao_nenhum_achado_desaparece():
    achados = [achado(linha=10), achado(linha=12, categoria="testes"), achado(arquivo="B.java", linha=1)]
    grupos = pre_consolidar(achados)
    assert sum(len(g.achados) for g in grupos) == len(achados)


def test_grupo_guarda_arquivo_e_menor_linha():
    grupos = pre_consolidar([achado(linha=15), achado(linha=12, categoria="testes")])
    assert len(grupos) == 1
    assert grupos[0].linha == 12


def test_lista_vazia():
    assert pre_consolidar([]) == []
