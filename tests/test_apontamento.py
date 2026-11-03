import pytest

from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade, Status, TransicaoInvalida


def novo(**kw) -> Apontamento:
    base = dict(revisao_id=1, arquivo="A.java", caminho_antigo="A.java", linha=10, linha_antiga=None,
                severidade=Severidade.P1, confianca=7, texto_original="texto", trecho="")
    return Apontamento(**{**base, **kw})


def test_aprovar_com_edicao_guarda_texto_final_e_preserva_original():
    ap = novo()
    ap.aprovar("  texto editado  ")
    assert ap.status == Status.APROVADO
    assert ap.texto_final == "texto editado"
    assert ap.texto_original == "texto"


def test_aprovar_com_texto_vazio_falha():
    with pytest.raises(TransicaoInvalida):
        novo().aprovar("   ")


def test_rejeitar_e_reabrir():
    ap = novo()
    ap.rejeitar(MotivoRejeicao.FALSO_POSITIVO)
    assert (ap.status, ap.motivo_rejeicao) == (Status.REJEITADO, MotivoRejeicao.FALSO_POSITIVO)
    ap.reabrir()
    assert (ap.status, ap.motivo_rejeicao) == (Status.PENDENTE, None)


def test_pendente_nao_pode_ser_publicado():
    ap = novo()
    assert not ap.pode_publicar
    with pytest.raises(TransicaoInvalida):
        ap.marcar_publicado("d1")


def test_fluxo_falha_e_retry_ate_publicar():
    ap = novo()
    ap.aprovar()
    ap.marcar_falha("timeout")
    assert ap.pode_publicar and ap.status == Status.FALHA_PUBLICACAO
    ap.marcar_publicado("d1")
    assert ap.status == Status.PUBLICADO and ap.erro is None
    assert not ap.pode_publicar


def test_publicado_e_terminal():
    ap = novo()
    ap.aprovar()
    ap.marcar_publicado("d1")
    for acao in (ap.aprovar, ap.reabrir, lambda: ap.rejeitar(MotivoRejeicao.OUTRO), ap.marcar_desatualizado):
        with pytest.raises(TransicaoInvalida):
            acao()


def test_rejeitado_nao_pode_ser_aprovado_sem_reabrir():
    ap = novo()
    ap.rejeitar(MotivoRejeicao.TOM)
    with pytest.raises(TransicaoInvalida):
        ap.aprovar()
