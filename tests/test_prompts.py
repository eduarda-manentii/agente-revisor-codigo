from revisor import prompts
from revisor.dominio.modelos import GERAL, Guia, MapaProjeto
from tests.fakes import PERFIL_BACK


def ex(n: int, tamanho: int = 500, projeto: str = "p", autor: str = "fulana") -> "object":
    from revisor.dominio.modelos import Exemplo
    return Exemplo("back", projeto, 1, n, "A.java", 1, "x" * tamanho, f"comentário {n}", True,
                   autor=autor, criado_em="2025-01-01T00:00:00Z")


def guia(conteudo: str, escopo: str = GERAL, versao: int = 1) -> Guia:
    return Guia(perfil="back", escopo=escopo, versao=versao, conteudo=conteudo, exemplos_usados=1,
                criado_em="2025-01-01T00:00:00")


def test_dividir_em_lotes_nao_descarta_nada_e_respeita_orcamento():
    exemplos = [ex(i) for i in range(50)]
    lotes = prompts.dividir_em_lotes(exemplos, limite_caracteres=2_000)
    assert len(lotes) > 1
    assert [e for lote in lotes for e in lote] == exemplos


def test_exemplo_maior_que_o_orcamento_vai_sozinho_em_um_lote():
    lotes = prompts.dividir_em_lotes([ex(1, 5_000), ex(2, 10)], limite_caracteres=1_000)
    assert [len(l) for l in lotes] == [1, 1]


def test_destilacao_inclui_guia_atual_ou_marca_primeiro_lote():
    assert "primeiro lote" in prompts.usuario_destilacao(None, [ex(1)], [])
    assert "GUIA EXISTENTE" in prompts.usuario_destilacao("GUIA EXISTENTE", [ex(1)], [])


def test_exemplo_formatado_tem_cabecalho_com_note_id_autor_e_projeto():
    usuario = prompts.usuario_destilacao(None, [ex(42, projeto="g/divida", autor="fulana")], [])
    assert "[#42] autor: fulana | projeto: g/divida | arquivo: A.java" in usuario


def test_sistema_destilacao_proibe_remover_padroes():
    assert "NUNCA remova" in prompts.sistema_destilacao(GERAL)
    assert "### <título" in prompts.sistema_destilacao(GERAL)


def test_sistema_destilacao_geral_e_micro_tem_focos_diferentes():
    geral = prompts.sistema_destilacao(GERAL)
    micro = prompts.sistema_destilacao("g/divida")
    assert "GUIA GERAL" in geral
    assert "g/divida" in micro and "PARTICULAR deste projeto" in micro


def test_sistema_revisao_sem_guia_nao_menciona_secao_de_guia():
    sistema = prompts.sistema_revisao(PERFIL_BACK, None)
    assert "instruções back" in sistema
    assert "Guia geral" not in sistema
    assert "array JSON" in sistema


def test_sistema_revisao_monta_guia_geral_micro_e_mapa_na_ordem():
    sistema = prompts.sistema_revisao(
        PERFIL_BACK, guia("PADRÃO GERAL"), guia("PADRÃO DO MICRO", escopo="g/divida"),
        MapaProjeto(projeto="g/divida", sha="s1", conteudo="MAPA TÉCNICO", arquivos_lidos=(), criado_em="x"),
    )
    assert sistema.index("instruções back") < sistema.index("PADRÃO GERAL") < sistema.index(
        "PADRÃO DO MICRO"
    ) < sistema.index("MAPA TÉCNICO") < sistema.index("array JSON")
    assert "prevalece sobre o guia geral" in sistema


def test_usuario_revisao_inclui_bloco_de_arquivo_completo_antes_do_diff():
    from tests.fakes import DIFF_SERVICE, arquivo
    arq = arquivo("A.java", DIFF_SERVICE)
    usuario = prompts.usuario_revisao("t", "d", [arq], [], {"A.java": "conteudo completo do arquivo"})
    assert usuario.index("# Arquivo completo (versão do MR): A.java") < usuario.index("# Diff a revisar")
    assert "conteudo completo do arquivo" in usuario


def test_usuario_mapa_e_sistema_mapa():
    usuario = prompts.usuario_mapa("g/divida", [("Service.java", "class X {}")], ["src/main", "src/test"])
    assert "# Projeto: g/divida" in usuario
    assert "### arquivo: Service.java" in usuario
    assert "src/main" in usuario
    assert "só com o mapa" in prompts.sistema_mapa()
