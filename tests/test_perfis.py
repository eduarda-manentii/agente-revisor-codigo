from pathlib import Path

import pytest

from revisor.dominio.modelos import carregar_agentes, carregar_perfis

RAIZ = Path(__file__).resolve().parent.parent


def test_perfis_do_projeto_carregam():
    perfis = carregar_perfis(RAIZ / "perfis")
    assert set(perfis) == {"back", "front"}
    assert perfis["back"].aceita("src/main/java/Contrato.JAVA")
    assert not perfis["back"].aceita("app.component.ts")
    assert perfis["front"].aceita("app.component.ts")


def test_perfil_sem_ignorar_arquivos_tem_default_vazio():
    perfis = carregar_perfis(RAIZ / "perfis")
    assert perfis["back"].ignorar_arquivos == () and perfis["back"].nunca_ignorar == ()


def test_perfil_le_ignorar_arquivos_e_nunca_ignorar_do_toml(tmp_path):
    (tmp_path / "instrucoes.md").write_text("Instruções.", encoding="utf-8")
    (tmp_path / "x.toml").write_text(
        'nome = "x"\nextensoes = [".java"]\ninstrucoes_arquivo = "instrucoes.md"\n'
        'ignorar_arquivos = ["src/gerado/*"]\nnunca_ignorar = ["package-lock.json"]\n',
        encoding="utf-8",
    )
    perfil = carregar_perfis(tmp_path)["x"]
    assert perfil.ignorar_arquivos == ("src/gerado/*",)
    assert perfil.nunca_ignorar == ("package-lock.json",)


def test_perfil_back_e_so_java():
    perfis = carregar_perfis(RAIZ / "perfis")
    back = perfis["back"]
    assert back.descricao == "Java / Spring"
    assert back.extensoes == (".java", ".xml", ".sql", ".yml", ".yaml", ".properties")
    assert not back.aceita("Script.py")
    assert not back.aceita("Classe.kt")
    assert back.instrucoes.splitlines()[0] == "Revise como Tech Lead de backend Java / Spring."


# ---------- v3 R3: agentes especialistas ----------

def test_perfil_le_agentes_por_nivel_e_sobrescrita_de_modelo():
    back = carregar_perfis(RAIZ / "perfis")["back"]
    assert back.agentes_do_nivel("TRIVIAL") == ("generalista",)
    assert back.agentes_do_nivel("COMPLETO") == (
        "qualidade", "estilo-revisor", "testes", "seguranca", "performance"
    )
    assert back.agentes_do_nivel("INEXISTENTE") == ()
    assert back.modelo_por_agente == {"seguranca": "opus"}


def test_carregar_agentes_do_projeto():
    agentes = carregar_agentes(RAIZ / "perfis" / "agentes")
    assert set(agentes) == {
        "generalista", "qualidade", "estilo-revisor", "testes", "seguranca", "performance",
    }
    assert "Regras comuns" in agentes["qualidade"].instrucoes


def test_carregar_agentes_rejeita_arquivo_sem_o_que_nao_apontar(tmp_path):
    (tmp_path / "ruim.md").write_text("## O que apontar\n\nalgo", encoding="utf-8")
    with pytest.raises(ValueError, match="O que NÃO apontar"):
        carregar_agentes(tmp_path)


def test_carregar_agentes_concatena_regras_comuns(tmp_path):
    (tmp_path / "REGRAS_COMUNS.md").write_text("REGRA COMUM X", encoding="utf-8")
    (tmp_path / "foo.md").write_text("## O que apontar\n\na\n\n## O que NÃO apontar\n\nb", encoding="utf-8")
    agentes = carregar_agentes(tmp_path)
    assert "REGRA COMUM X" in agentes["foo"].instrucoes
