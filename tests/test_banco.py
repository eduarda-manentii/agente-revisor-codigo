from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade, Status
from revisor.dominio.modelos import Exemplo, Revisao


def test_round_trip_apontamento_com_enums_e_nulos(repo):
    revisao_id = repo.criar_revisao(Revisao("u", "g/p", 1, "back"))
    ap = Apontamento(revisao_id, "A.java", "A.java", 10, None, Severidade.P0, 9, "txt", "trecho")
    repo.adicionar_apontamentos([ap])
    ap.rejeitar(MotivoRejeicao.TOM)
    repo.salvar_apontamento(ap)
    lido = repo.obter_apontamento(ap.id)
    assert lido == ap
    assert lido.status == Status.REJEITADO and lido.motivo_rejeicao == MotivoRejeicao.TOM


def test_exemplo_duplicado_e_ignorado(repo):
    ex = Exemplo("back", "g/p", 1, 42, "A.java", 3, "t", "comentário", True)
    assert repo.salvar_exemplo(ex) is True
    assert repo.salvar_exemplo(ex) is False
    assert repo.contar_exemplos("back") == 1
    # mesma nota em outro perfil é outro exemplo
    assert repo.salvar_exemplo(Exemplo("front", "g/p", 1, 42, "A.ts", 3, "t", "c", True)) is True


def test_exemplos_acolhidos_vem_primeiro(repo):
    repo.salvar_exemplo(Exemplo("back", "p", 1, 1, "A", 1, "t", "c1", False))
    repo.salvar_exemplo(Exemplo("back", "p", 1, 2, "A", 1, "t", "c2", True))
    assert [e.note_id for e in repo.listar_exemplos("back")] == [2, 1]


def test_guia_versiona_por_perfil_e_guarda_historico(repo):
    assert repo.salvar_guia("back", "v1", [], []) == 1
    assert repo.salvar_guia("back", "v2", [], []) == 2
    assert repo.salvar_guia("front", "f1", [], []) == 1
    assert repo.guia_ativo("back").conteudo == "v2"
    assert repo.guia_por_versao("back", 1).conteudo == "v1"
    assert [g.versao for g in repo.listar_versoes_guia("back")] == [2, 1]
    assert repo.guia_ativo("inexistente") is None


def test_salvar_guia_marca_incorporados_e_conta_acumulado(repo):
    for n in (1, 2, 3):
        repo.salvar_exemplo(Exemplo("back", "p", 1, n, "A", 1, "t", f"c{n}", False))
    repo.salvar_guia("back", "v1", [1, 2], [])
    assert [e.note_id for e in repo.listar_exemplos_pendentes("back")] == [3]
    repo.salvar_guia("back", "v2", [3], [])
    assert repo.contar_exemplos_pendentes("back") == 0
    assert repo.guia_ativo("back").exemplos_usados == 3


def test_checkpoint_por_projeto(repo):
    assert repo.checkpoint("back", "g/api") is None
    repo.salvar_checkpoint("back", "g/api", "2026-01-01")
    repo.salvar_checkpoint("back", "g/api", "2026-02-01")
    assert repo.checkpoint("back", "g/api") == "2026-02-01"
    assert repo.checkpoint("back", "g/web") is None


def test_execucoes_interrompidas_viram_erro(repo):
    from revisor.dominio.modelos import Treino
    repo.criar_revisao(Revisao("u", "g/p", 1, "back"))
    repo.criar_treino(Treino("back"))
    repo.marcar_execucoes_interrompidas()
    assert repo.listar_revisoes()[0].status == "ERRO"
    assert repo.ultimo_treino("back").status == "ERRO"


def test_migra_banco_da_versao_anterior(tmp_path):
    import sqlite3
    from revisor.adaptadores.banco import RepositorioSQLite
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript("""
        CREATE TABLE exemplos (id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, projeto TEXT NOT NULL,
            mr_iid INTEGER NOT NULL, note_id INTEGER NOT NULL, arquivo TEXT NOT NULL, linha INTEGER,
            trecho TEXT, comentario TEXT NOT NULL, resolvido INTEGER NOT NULL, UNIQUE (perfil, note_id));
        INSERT INTO exemplos VALUES (1, 'back', 'p', 1, 7, 'A', 1, 't', 'comentário antigo', 1);
    """)
    con.close()
    repo = RepositorioSQLite(caminho)
    assert [e.note_id for e in repo.listar_exemplos_pendentes("back")] == [7]  # dado antigo preservado
