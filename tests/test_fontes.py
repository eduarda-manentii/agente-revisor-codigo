from revisor.dominio.fontes import Fontes, TipoFonte, parse_ids, verificar_fontes


def test_parse_ids_aceita_int_string_e_hash_e_ignora_nao_numero():
    assert parse_ids([123, "456", "#789", "abc", "#  "]) == [123, 456, 789]


def test_id_existente_confirmado_e_inventado_descartado():
    fontes = verificar_fontes(
        comentarios_citados=[1, 999], padrao_guia="", regra_perfil="",
        note_ids_existentes={1, 2, 3}, textos_guia=[], instrucoes="",
    )
    assert fontes.comentarios == (1,)
    assert fontes.comentarios_nao_confirmados == (999,)
    assert fontes.tem_citacao_nao_confirmada


def test_duplicados_sao_removidos_preservando_ordem():
    fontes = verificar_fontes(
        comentarios_citados=[1, 2, 1, 2], padrao_guia="", regra_perfil="",
        note_ids_existentes={1, 2}, textos_guia=[], instrucoes="",
    )
    assert fontes.comentarios == (1, 2)


def test_padrao_do_guia_confirmado_so_se_texto_existir_normalizado():
    fontes = verificar_fontes(
        comentarios_citados=[], padrao_guia="Mass Assignment  no   DTO", regra_perfil="",
        note_ids_existentes=set(), textos_guia=["### Mass assignment no dto\nFontes: #1"],
        instrucoes="",
    )
    assert fontes.padrao_confirmado

    fontes_falso = verificar_fontes(
        comentarios_citados=[], padrao_guia="Padrão que não existe", regra_perfil="",
        note_ids_existentes=set(), textos_guia=["### Outro padrão qualquer"], instrucoes="",
    )
    assert not fontes_falso.padrao_confirmado


def test_regra_do_perfil_confirmada_so_se_trecho_existir():
    fontes = verificar_fontes(
        comentarios_citados=[], padrao_guia="", regra_perfil="URLs REST em kebab-case",
        note_ids_existentes=set(), textos_guia=[], instrucoes="Use URLs REST em kebab-case e plural.",
    )
    assert fontes.regra_confirmada
    assert not verificar_fontes(
        [], "", "Regra inventada", set(), [], "instruções reais"
    ).regra_confirmada


def test_nada_embasado_e_sem_precedente():
    fontes = verificar_fontes([], "", "", set(), [], "")
    assert fontes.sem_precedente
    assert fontes.tipos == ()


def test_com_alguma_fonte_confirmada_nao_e_sem_precedente():
    fontes = Fontes(comentarios=(1,), registrada=True)
    assert not fontes.sem_precedente
    assert TipoFonte.COMENTARIO in fontes.tipos


def test_fontes_nao_registrada_e_apontamento_anterior_a_versao():
    antiga = Fontes(registrada=False)
    assert not antiga.registrada
    assert antiga.sem_precedente  # mas o motivo é "não registrada", distinto de SEM_PRECEDENTE real
