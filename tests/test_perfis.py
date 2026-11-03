from pathlib import Path

from revisor.dominio.modelos import carregar_perfis

RAIZ = Path(__file__).resolve().parent.parent


def test_perfis_do_projeto_carregam():
    perfis = carregar_perfis(RAIZ / "perfis")
    assert set(perfis) == {"back", "front"}
    assert perfis["back"].aceita("src/main/java/Contrato.JAVA")
    assert not perfis["back"].aceita("app.component.ts")
    assert perfis["front"].aceita("app.component.ts")


def test_perfil_back_e_so_java():
    perfis = carregar_perfis(RAIZ / "perfis")
    back = perfis["back"]
    assert back.descricao == "Java / Spring"
    assert back.extensoes == (".java", ".xml", ".sql", ".yml", ".yaml", ".properties")
    assert not back.aceita("Script.py")
    assert not back.aceita("Classe.kt")
    assert back.instrucoes.splitlines()[0] == "Revise como Tech Lead de backend Java / Spring."
