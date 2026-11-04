import json

import pytest

from revisor.dominio.agentes import parse_achados
from revisor.dominio.apontamento import Severidade


def achado(arquivo="A.java", linha=12, severidade="P1", confianca=8,
          comentario="Problema real", evidencia="trecho lido") -> dict:
    return {"arquivo": arquivo, "linha": linha, "severidade": severidade,
            "confianca": confianca, "comentario": comentario, "evidencia": evidencia}


def test_parse_achados_validos():
    validos, descartados = parse_achados(json.dumps([achado(), achado(linha=13)]), "qualidade")
    assert len(validos) == 2 and descartados == 0
    assert validos[0].categoria == "qualidade"
    assert validos[0].severidade == Severidade.P1


def test_achado_sem_evidencia_e_descartado():
    validos, descartados = parse_achados(json.dumps([{**achado(), "evidencia": ""}]), "qualidade")
    assert validos == [] and descartados == 1


def test_json_malformado_levanta_value_error():
    with pytest.raises(ValueError):
        parse_achados("isso não é um array json nenhum", "qualidade")


def test_severidade_invalida_e_descartada():
    validos, descartados = parse_achados(json.dumps([{**achado(), "severidade": "P9"}]), "qualidade")
    assert validos == [] and descartados == 1


def test_campo_faltando_e_descartado():
    item = achado()
    del item["linha"]
    validos, descartados = parse_achados(json.dumps([item]), "qualidade")
    assert validos == [] and descartados == 1


def test_lista_vazia():
    assert parse_achados("[]", "qualidade") == ([], 0)
