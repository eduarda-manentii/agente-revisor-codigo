import pytest

from revisor.aplicacao.revisar import RevisarMR
from revisor.dominio.apontamento import Severidade
from revisor.dominio.modelos import GERAL, Exemplo, MapaProjeto, StatusExecucao
from tests.fakes import (DIFF_COMPONENTE, DIFF_SERVICE, PERFIS, FakeGitLab, FakeLLM, arquivo,
                         dados_mr, sugestao)

URL = "https://gitlab.empresa.com/grupo/api/-/merge_requests/7"


def caso(repo, gitlab=None, llm=None, **kw):
    gitlab = gitlab or FakeGitLab()
    llm = llm or FakeLLM([])
    return RevisarMR(gitlab, llm, repo, PERFIS, "gitlab.empresa.com", **kw), gitlab, llm


def rodar(uc, repo, perfil="back"):
    revisao_id = uc.iniciar(URL, perfil)
    uc.executar(revisao_id)
    return repo.obter_revisao(revisao_id), repo.listar_apontamentos(revisao_id)


def test_gera_apontamento_valido_com_trecho_e_shas(repo):
    uc, _, _ = caso(repo, llm=FakeLLM([sugestao()]))
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert (revisao.base_sha, revisao.start_sha, revisao.head_sha) == ("b1", "s1", "h1")
    assert len(aps) == 1
    assert aps[0].linha == 12 and aps[0].linha_antiga is None  # linha adicionada
    assert ">   12 +" in aps[0].trecho


def test_linha_de_contexto_guarda_linha_antiga(repo):
    uc, _, _ = caso(repo, llm=FakeLLM([sugestao(linha=14)]))
    _, aps = rodar(uc, repo)
    assert aps[0].linha_antiga == 12


def test_descarta_alucinacao_baixa_confianca_e_duplicata(repo):
    respostas = [
        sugestao(),                                  # válido
        sugestao(),                                  # duplicado
        sugestao(linha=999),                         # linha fora do diff
        sugestao(arquivo="Inexistente.java"),        # arquivo fora do lote
        sugestao(linha=13, confianca=3),             # abaixo da confiança mínima
    ]
    uc, _, _ = caso(repo, llm=FakeLLM(respostas))
    revisao, aps = rodar(uc, repo)
    assert len(aps) == 1
    assert revisao.descartados == 4


def test_ordena_por_severidade_e_corta_no_maximo_do_perfil(repo):
    respostas = [sugestao(linha=11, severidade="P2", comentario=f"c{i}") for i in range(12)]
    respostas.append(sugestao(linha=12, severidade="P0", comentario="crítico"))
    uc, _, _ = caso(repo, llm=FakeLLM(respostas))
    _, aps = rodar(uc, repo)
    assert len(aps) == 10  # max_apontamentos do PERFIL_BACK
    assert any(a.severidade == Severidade.P0 for a in aps)


def test_filtra_arquivos_pelo_perfil(repo):
    mr = dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE), arquivo("lista.component.ts", DIFF_COMPONENTE))
    uc, _, llm = caso(repo, gitlab=FakeGitLab(mr=mr), llm=FakeLLM([]))
    rodar(uc, repo, perfil="front")
    _, prompt_usuario = llm.chamadas[0]
    assert "lista.component.ts" in prompt_usuario
    assert "ContratoService.java" not in prompt_usuario


def test_sem_arquivos_do_perfil_nao_chama_llm(repo):
    mr = dados_mr(arquivo("lista.component.ts", DIFF_COMPONENTE))
    uc, _, llm = caso(repo, gitlab=FakeGitLab(mr=mr))
    revisao, _ = rodar(uc, repo, perfil="back")
    assert llm.chamadas == []
    assert revisao.status == StatusExecucao.CONCLUIDA and "Nenhum arquivo" in revisao.nota


def test_arquivo_removido_e_ignorado(repo):
    mr = dados_mr(arquivo("Velho.java", DIFF_SERVICE, removido=True))
    uc, _, llm = caso(repo, gitlab=FakeGitLab(mr=mr))
    rodar(uc, repo)
    assert llm.chamadas == []


def test_divide_em_lotes_quando_passa_do_orcamento(repo):
    mr = dados_mr(arquivo("A.java", DIFF_SERVICE), arquivo("B.java", DIFF_SERVICE))
    uc, _, llm = caso(repo, gitlab=FakeGitLab(mr=mr), llm=FakeLLM([], []), max_caracteres_lote=50)
    rodar(uc, repo)
    assert len(llm.chamadas) == 2


def test_usa_guia_e_exemplos_parecidos_no_prompt(repo):
    repo.salvar_guia("back", GERAL, "GUIA: cobrar status do contexto", [], [])
    repo.salvar_exemplo(Exemplo("back", "p", 1, 99, "X.java", 5, "pedido.setStatus(request.getStatus())",
                                "Nunca aceite status do request.", True))
    uc, _, llm = caso(repo, llm=FakeLLM([]))
    revisao, _ = rodar(uc, repo)
    sistema, usuario = llm.chamadas[0]
    assert "GUIA: cobrar status do contexto" in sistema
    assert "Nunca aceite status do request." in usuario
    assert revisao.guia_versao == 1


def test_resposta_invalida_do_llm_marca_erro(repo):
    uc, _, _ = caso(repo, llm=FakeLLM("desculpe, não consigo"))
    revisao, _ = rodar(uc, repo)
    assert revisao.status == StatusExecucao.ERRO
    assert "JSON" in revisao.erro


@pytest.mark.parametrize("url,perfil", [
    ("https://outro.gitlab.com/g/p/-/merge_requests/1", "back"),
    (URL, "inexistente"),
    ("não é url", "back"),
])
def test_iniciar_valida_entrada(repo, url, perfil):
    uc, _, _ = caso(repo)
    with pytest.raises(ValueError):
        uc.iniciar(url, perfil)


# ---------- R3/R5: guia geral + guia do micro + mapa técnico no prompt ----------

def test_prompt_usa_guia_geral_guia_do_micro_e_mapa_do_projeto_do_mr(repo):
    repo.salvar_guia("back", GERAL, "GUIA GERAL", [], [])
    repo.salvar_guia("back", "grupo/api", "GUIA DO MICRO grupo/api", [], [])
    repo.salvar_guia("back", "grupo/outro", "GUIA DE OUTRO MICRO", [], [])
    repo.salvar_mapa(MapaProjeto(projeto="grupo/api", sha="s1", conteudo="MAPA TECNICO grupo/api",
                                 arquivos_lidos=(), criado_em="2025-01-01T00:00:00"))
    uc, _, llm = caso(repo, llm=FakeLLM([]))
    revisao, _ = rodar(uc, repo)
    sistema, _ = llm.chamadas[0]
    assert "GUIA GERAL" in sistema
    assert "GUIA DO MICRO grupo/api" in sistema
    assert "GUIA DE OUTRO MICRO" not in sistema
    assert "MAPA TECNICO grupo/api" in sistema
    assert revisao.guia_versao == 1 and revisao.guia_micro_versao == 1
    assert revisao.mapa_em == "2025-01-01T00:00:00"


# ---------- R5: contexto completo (arquivo inteiro no head_sha do MR) ----------

def test_arquivo_completo_entra_no_prompt_antes_do_diff(repo):
    mr = dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE), head="headsha")
    gitlab = FakeGitLab(mr=mr, conteudos_arquivo={
        ("grupo/api", "src/ContratoService.java", "headsha"): "conteudo completo do arquivo",
    })
    uc, _, llm = caso(repo, gitlab=gitlab, llm=FakeLLM([]))
    rodar(uc, repo)
    _, usuario = llm.chamadas[0]
    assert "# Arquivo completo (versão do MR): src/ContratoService.java" in usuario
    assert "conteudo completo do arquivo" in usuario
    assert usuario.index("# Arquivo completo") < usuario.index("# Diff a revisar")


def test_arquivo_maior_que_40000_caracteres_vai_so_com_diff(repo):
    mr = dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE), head="headsha")
    gitlab = FakeGitLab(mr=mr, conteudos_arquivo={
        ("grupo/api", "src/ContratoService.java", "headsha"): "x" * 40_001,
    })
    uc, _, llm = caso(repo, gitlab=gitlab, llm=FakeLLM([]))
    rodar(uc, repo)
    _, usuario = llm.chamadas[0]
    assert "# Arquivo completo" not in usuario


# ---------- R6: "por quê" — motivo e fontes verificadas ----------

def test_fonte_de_comentario_confirmada_aparece_no_apontamento(repo):
    repo.salvar_exemplo(Exemplo("back", "grupo/api", 1, 55, "X.java", 1, "t", "c", False))
    uc, _, _ = caso(repo, llm=FakeLLM([
        sugestao(motivo="por causa disso",
                 fontes={"comentarios": [55], "padrao_guia": "", "regra_perfil": ""})
    ]))
    _, aps = rodar(uc, repo)
    assert aps[0].motivo == "por causa disso"
    assert aps[0].fontes.comentarios == (55,)
    assert not aps[0].fontes.sem_precedente


def test_fonte_de_comentario_inventada_fica_nao_confirmada(repo):
    uc, _, _ = caso(repo, llm=FakeLLM([
        sugestao(fontes={"comentarios": [999], "padrao_guia": "", "regra_perfil": ""})
    ]))
    _, aps = rodar(uc, repo)
    assert aps[0].fontes.comentarios == ()
    assert aps[0].fontes.comentarios_nao_confirmados == (999,)
    assert aps[0].fontes.sem_precedente


def test_padrao_do_guia_confirmado_so_se_texto_existir_no_guia(repo):
    repo.salvar_guia("back", GERAL, "### Mass assignment\nFontes: #1", [], [])
    uc, _, _ = caso(repo, llm=FakeLLM([
        sugestao(fontes={"comentarios": [], "padrao_guia": "Mass assignment", "regra_perfil": ""})
    ]))
    _, aps = rodar(uc, repo)
    assert aps[0].fontes.padrao_confirmado


def test_sem_nenhuma_fonte_citada_e_sem_precedente(repo):
    uc, _, _ = caso(repo, llm=FakeLLM([sugestao()]))
    _, aps = rodar(uc, repo)
    assert aps[0].fontes.sem_precedente
