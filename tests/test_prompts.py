from revisor import prompts
from revisor.dominio.modelos import Exemplo
from tests.fakes import PERFIL_BACK


def ex(n: int, tamanho: int = 500) -> Exemplo:
    return Exemplo("back", "p", 1, n, "A.java", 1, "x" * tamanho, f"comentário {n}", True)


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


def test_sistema_destilacao_proibe_remover_padroes():
    assert "NUNCA remova" in prompts.sistema_destilacao()


def test_sistema_revisao_sem_guia_nao_menciona_secao_de_guia():
    sistema = prompts.sistema_revisao(PERFIL_BACK, None)
    assert "instruções back" in sistema
    assert "Guia do revisor" not in sistema
    assert "array JSON" in sistema
