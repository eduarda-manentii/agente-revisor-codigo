from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade, Status
from revisor.dominio.fontes import Fontes
from revisor.dominio.modelos import GERAL, Exemplo, MapaProjeto, Revisao


def test_round_trip_apontamento_com_enums_e_nulos(repo):
    revisao_id = repo.criar_revisao(Revisao("u", "g/p", 1, "back"))
    ap = Apontamento(revisao_id, "A.java", "A.java", 10, None, Severidade.P0, 9, "txt", "trecho")
    repo.adicionar_apontamentos([ap])
    ap.rejeitar(MotivoRejeicao.TOM)
    repo.salvar_apontamento(ap)
    lido = repo.obter_apontamento(ap.id)
    assert lido.fontes == Fontes(registrada=False)  # nunca setado: apontamento "sem versão"
    ap.fontes = Fontes(registrada=False)
    assert lido == ap
    assert lido.status == Status.REJEITADO and lido.motivo_rejeicao == MotivoRejeicao.TOM


def test_apontamento_com_motivo_e_fontes_persiste_e_recarrega(repo):
    revisao_id = repo.criar_revisao(Revisao("u", "g/p", 1, "back"))
    fontes = Fontes(
        comentarios=(1, 2), comentarios_nao_confirmados=(99,), padrao_guia="Título do padrão",
        padrao_confirmado=True, regra_perfil="trecho exato", regra_confirmada=True, registrada=True,
    )
    ap = Apontamento(revisao_id, "A.java", "A.java", 10, None, Severidade.P1, 7, "txt", "trecho",
                     motivo="por que é um problema", fontes=fontes)
    repo.adicionar_apontamentos([ap])
    lido = repo.obter_apontamento(ap.id)
    assert lido.motivo == "por que é um problema"
    assert lido.fontes == fontes


def test_exemplo_duplicado_e_ignorado(repo):
    ex = Exemplo("back", "g/p", 1, 42, "A.java", 3, "t", "comentário", True, autor="fulana")
    assert repo.salvar_exemplo(ex) is True
    assert repo.salvar_exemplo(ex) is False
    assert repo.contar_exemplos("back") == 1
    # mesma nota em outro perfil é outro exemplo
    assert repo.salvar_exemplo(Exemplo("front", "g/p", 1, 42, "A.ts", 3, "t", "c", True)) is True


def test_exemplos_acolhidos_vem_primeiro(repo):
    repo.salvar_exemplo(Exemplo("back", "p", 1, 1, "A", 1, "t", "c1", False))
    repo.salvar_exemplo(Exemplo("back", "p", 1, 2, "A", 1, "t", "c2", True))
    assert [e.note_id for e in repo.listar_exemplos("back")] == [2, 1]


def test_exemplo_guarda_autor_e_criado_em(repo):
    repo.salvar_exemplo(Exemplo("back", "p", 1, 1, "A", 1, "t", "c1", False, autor="fulana",
                                criado_em="2025-01-01T00:00:00Z"))
    ex = repo.listar_exemplos("back")[0]
    assert ex.autor == "fulana" and ex.criado_em == "2025-01-01T00:00:00Z"


def test_guia_versiona_por_perfil_e_escopo_e_guarda_historico(repo):
    assert repo.salvar_guia("back", GERAL, "v1", [], []) == 1
    assert repo.salvar_guia("back", GERAL, "v2", [], []) == 2
    assert repo.salvar_guia("front", GERAL, "f1", [], []) == 1
    assert repo.salvar_guia("back", "g/divida", "m1", [], []) == 1  # versão própria por escopo
    assert repo.guia_ativo("back").conteudo == "v2"
    assert repo.guia_ativo("back", "g/divida").conteudo == "m1"
    assert repo.guia_por_versao("back", 1).conteudo == "v1"
    assert [g.versao for g in repo.listar_versoes_guia("back")] == [2, 1]
    assert repo.guia_ativo("inexistente") is None
    assert repo.listar_escopos_guia("back") == ["g/divida"]


def test_salvar_guia_marca_incorporados_e_conta_acumulado(repo):
    for n in (1, 2, 3):
        repo.salvar_exemplo(Exemplo("back", "p", 1, n, "A", 1, "t", f"c{n}", False))
    repo.salvar_guia("back", GERAL, "v1", [1, 2], [])
    assert [e.note_id for e in repo.listar_exemplos_pendentes("back", GERAL)] == [3]
    repo.salvar_guia("back", GERAL, "v2", [3], [])
    assert repo.contar_exemplos_pendentes("back") == 0
    assert repo.guia_ativo("back").exemplos_usados == 3


def test_camadas_geral_e_micro_controlam_pendencia_separadamente(repo):
    repo.salvar_exemplo(Exemplo("back", "g/divida", 1, 1, "A", 1, "t", "c1", False))
    repo.salvar_guia("back", GERAL, "v1", [1], [])
    # incorporado ao geral, mas ainda pendente para o guia do micro (coluna separada)
    assert repo.listar_exemplos_pendentes("back", GERAL) == []
    assert [e.note_id for e in repo.listar_exemplos_pendentes("back", "g/divida")] == [1]
    repo.salvar_guia("back", "g/divida", "m1", [1], [])
    assert repo.listar_exemplos_pendentes("back", "g/divida") == []
    assert repo.guia_ativo("back", "g/divida").exemplos_usados == 1


def test_salvar_guia_marca_apontamento_rejeitado_como_incorporado(repo):
    revisao_id = repo.criar_revisao(Revisao("u", "g/p", 1, "back"))
    ap = Apontamento(revisao_id, "A.java", "A.java", 1, None, Severidade.P2, 5, "x", "t")
    repo.adicionar_apontamentos([ap])
    ap.rejeitar(MotivoRejeicao.IRRELEVANTE)
    repo.salvar_apontamento(ap)
    assert len(repo.listar_rejeitados_pendentes("back")) == 1
    repo.salvar_guia("back", GERAL, "v1", [], [ap.id])
    assert repo.listar_rejeitados_pendentes("back") == []


def test_contar_exemplos_por_projeto(repo):
    repo.salvar_exemplo(Exemplo("back", "g/a", 1, 1, "A", 1, "t", "c", False))
    repo.salvar_exemplo(Exemplo("back", "g/a", 1, 2, "A", 1, "t", "c", False))
    repo.salvar_exemplo(Exemplo("back", "g/b", 1, 3, "A", 1, "t", "c", False))
    assert repo.contar_exemplos_por_projeto("back") == [("g/a", 2), ("g/b", 1)]


def test_obter_exemplos_preserva_ordem_pedida_e_ignora_inexistentes(repo):
    repo.salvar_exemplo(Exemplo("back", "p", 1, 5, "A", 1, "t", "c5", False))
    repo.salvar_exemplo(Exemplo("back", "p", 1, 9, "A", 1, "t", "c9", False))
    achados = repo.obter_exemplos("back", [9, 999, 5])
    assert [e.note_id for e in achados] == [9, 5]
    assert repo.obter_exemplos("back", []) == []


def test_salvar_e_recuperar_mapa_ativo_e_listar_mapas(repo):
    repo.salvar_mapa(MapaProjeto(projeto="g/a", sha="s1", conteudo="mapa 1", arquivos_lidos=("A.java",),
                                 criado_em="2025-01-01T00:00:00"))
    repo.salvar_mapa(MapaProjeto(projeto="g/a", sha="s2", conteudo="mapa 2", arquivos_lidos=("B.java",),
                                 criado_em="2025-02-01T00:00:00"))
    repo.salvar_mapa(MapaProjeto(projeto="g/b", sha="s1", conteudo="mapa b", arquivos_lidos=(),
                                 criado_em="2025-01-01T00:00:00"))
    assert repo.mapa_ativo("g/a").conteudo == "mapa 2"
    assert repo.mapa_ativo("g/a").arquivos_lidos == ("B.java",)
    assert repo.mapa_ativo("inexistente") is None
    assert {m.projeto: m.conteudo for m in repo.listar_mapas()} == {"g/a": "mapa 2", "g/b": "mapa b"}


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

        CREATE TABLE guias (id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, versao INTEGER NOT NULL,
            conteudo TEXT NOT NULL, exemplos_usados INTEGER NOT NULL, criado_em TEXT NOT NULL,
            UNIQUE (perfil, versao));
        INSERT INTO guias VALUES (1, 'back', 1, 'guia antigo', 1, '2024-01-01T00:00:00');

        CREATE TABLE apontamentos (id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL,
            arquivo TEXT NOT NULL, caminho_antigo TEXT NOT NULL, linha INTEGER NOT NULL,
            linha_antiga INTEGER, severidade TEXT NOT NULL, confianca INTEGER NOT NULL,
            texto_original TEXT NOT NULL, trecho TEXT, texto_final TEXT NOT NULL, status TEXT NOT NULL,
            motivo_rejeicao TEXT, discussion_id TEXT, erro TEXT);
        INSERT INTO apontamentos VALUES
            (1, 1, 'A', 'A', 1, NULL, 'P1', 7, 'x', 't', 'x', 'PENDENTE', NULL, NULL, NULL);

        CREATE TABLE treinos (id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, status TEXT NOT NULL,
            novos_exemplos INTEGER DEFAULT 0, guia_versao INTEGER, progresso TEXT, erro TEXT,
            iniciado_em TEXT NOT NULL, concluido_em TEXT);
        INSERT INTO treinos VALUES
            (1, 'back', 'CONCLUIDA', 1, 1, '', '', '2024-01-01T00:00:00', '2024-01-01T00:00:00');

        CREATE TABLE revisoes (id INTEGER PRIMARY KEY, mr_url TEXT NOT NULL, projeto TEXT NOT NULL,
            mr_iid INTEGER NOT NULL, perfil TEXT NOT NULL, status TEXT NOT NULL, titulo_mr TEXT,
            base_sha TEXT, start_sha TEXT, head_sha TEXT, guia_versao INTEGER,
            descartados INTEGER DEFAULT 0, nota TEXT, erro TEXT, criada_em TEXT NOT NULL);
        INSERT INTO revisoes VALUES
            (1, 'u', 'p', 1, 'back', 'CONCLUIDA', 't', 'b', 's', 'h', 1, 0, '', '', '2024-01-01T00:00:00');
    """)
    con.close()

    repo = RepositorioSQLite(caminho)

    # exemplo antigo preservado; colunas novas vêm vazias; ainda pendente no guia geral
    assert [e.note_id for e in repo.listar_exemplos_pendentes("back", GERAL)] == [7]
    exemplo = repo.listar_exemplos("back")[0]
    assert exemplo.autor == "" and exemplo.criado_em == ""

    # guia antigo (sem escopo) virou o guia GERAL; nenhum guia de micro existia
    assert repo.guia_ativo("back", GERAL).conteudo == "guia antigo"
    assert repo.listar_escopos_guia("back") == []

    # apontamento antigo (fontes nula) continua legível, marcado como "não registrado"
    ap = repo.obter_apontamento(1)
    assert ap.fontes.registrada is False and ap.motivo == ""

    # treino e revisão antigos continuam legíveis com as colunas novas vazias/nulas
    assert repo.obter_treino(1).avisos == ""
    revisao = repo.obter_revisao(1)
    assert revisao.guia_micro_versao is None and revisao.mapa_em == ""
