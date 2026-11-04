from datetime import datetime, timezone

import pytest

from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import TriarApontamento
from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade
from revisor.dominio.modelos import ComentarioHistorico, Revisao, StatusExecucao
from revisor.portas import ArvoreProjeto
from tests.fakes import PERFIS, FakeGitLab, FakeLLM


def comentario(note_id, arquivo="src/A.java", texto=None, projeto="g/api", autor="fulana",
               resolvido=True):
    texto = texto or f"Comentário real número {note_id} sobre setStatus."
    return ComentarioHistorico(projeto=projeto, mr_iid=1, note_id=note_id, arquivo=arquivo, linha=10,
                               comentario=texto, resolvido=resolvido, autor=autor,
                               criado_em="2025-01-01T00:00:00Z", trecho="trecho setStatus")


def treinar(repo, gitlab, llm, perfil="back", completo=False, grupos=None, projetos=None,
            excluir=None, **kw):
    uc = TreinarPerfil(
        gitlab, llm, repo, PERFIS, grupos or [],
        ["g/api", "g/web"] if projetos is None else projetos,
        excluir or set(), "2025-01-01", **kw,
    )
    treino_id = uc.iniciar(perfil, completo=completo)
    uc.executar(treino_id)
    return repo.obter_treino(treino_id)


# ---------- R1: descoberta de projetos pelo grupo ----------

def test_descobre_projetos_do_grupo_e_junta_com_avulsos_sem_duplicar(repo):
    gitlab = FakeGitLab(projetos_por_grupo={"g/micros": ["g/micros/b", "g/micros/a"]})
    treino = treinar(repo, gitlab, FakeLLM(), grupos=["g/micros"], projetos=["g/micros/b", "g/avulso"])
    assert treino.status == StatusExecucao.CONCLUIDA
    # ordem: projetos do grupo em ordem alfabética, depois avulsos, sem duplicar g/micros/b
    assert [p for p, _, _ in gitlab.consultas_comentarios] == ["g/micros/a", "g/micros/b", "g/avulso"]


def test_falha_em_um_projeto_vira_aviso_e_nao_trava_os_outros(repo):
    gitlab = FakeGitLab(comentarios=[comentario(1, projeto="g/web")], falhar_coleta={"g/api"})
    treino = treinar(repo, gitlab, FakeLLM("# Guia"), projetos=["g/api", "g/web"])
    assert treino.status == StatusExecucao.CONCLUIDA
    assert "g/api" in treino.avisos
    assert repo.checkpoint("back", "g/api") is None
    assert repo.checkpoint("back", "g/web") is not None
    assert treino.novos_exemplos == 1


def test_falha_em_todos_os_projetos_termina_em_erro(repo):
    gitlab = FakeGitLab(falhar_coleta={"g/api", "g/web"})
    treino = treinar(repo, gitlab, FakeLLM(), projetos=["g/api", "g/web"])
    assert treino.status == StatusExecucao.ERRO
    assert "403" in treino.erro


def test_grupo_inexistente_termina_em_erro(repo):
    gitlab = FakeGitLab(grupos_invalidos={"g/inexistente"})
    treino = treinar(repo, gitlab, FakeLLM(), grupos=["g/inexistente"], projetos=[])
    assert treino.status == StatusExecucao.ERRO
    assert "g/inexistente" in treino.erro


def test_nenhum_projeto_encontrado_termina_em_erro(repo):
    gitlab = FakeGitLab(projetos_por_grupo={"g/vazio": []})
    treino = treinar(repo, gitlab, FakeLLM(), grupos=["g/vazio"], projetos=[])
    assert treino.status == StatusExecucao.ERRO
    assert "Nenhum projeto" in treino.erro


# ---------- R2: aprender com todos os revisores ----------

def test_aprendizado_inclui_varios_autores_e_exclui_a_lista_de_excluidos(repo):
    gitlab = FakeGitLab(comentarios=[
        comentario(1, autor="fulana"),
        comentario(2, autor="beltrano"),
        comentario(3, autor="bot-ci"),
    ])
    treino = treinar(repo, gitlab, FakeLLM("# Guia"), excluir={"bot-ci"})
    autores = {e.autor for e in repo.listar_exemplos("back")}
    assert autores == {"fulana", "beltrano"}
    assert treino.novos_exemplos == 2


# ---------- fluxo de treino (coleta + incorporação ao guia geral) ----------

def test_coleta_filtra_por_perfil_e_ruido_e_gera_guia(repo):
    gitlab = FakeGitLab(comentarios=[
        comentario(1),
        comentario(2, arquivo="tela.component.ts"),  # outro perfil
        comentario(3, texto="lgtm"),                  # ruído
    ])
    treino = treinar(repo, gitlab, FakeLLM("# Guia v1"))
    assert treino.status == StatusExecucao.CONCLUIDA
    assert treino.novos_exemplos == 1 and treino.guia_versao == 1
    assert repo.guia_ativo("back").conteudo == "# Guia v1"


def test_novo_treino_funde_com_guia_atual_e_envia_so_comentarios_novos(repo):
    gitlab = FakeGitLab(comentarios=[comentario(1)])
    treinar(repo, gitlab, FakeLLM("# Guia com padrão A"))

    gitlab.comentarios.append(comentario(2, texto="Faltou teste do cenário de erro aqui."))
    llm = FakeLLM("# Guia com padrões A e B")
    treino = treinar(repo, gitlab, llm)

    _, prompt = llm.chamadas[0]
    assert "# Guia com padrão A" in prompt                     # parte do guia atual
    assert "Faltou teste do cenário de erro" in prompt          # inclui o novo
    assert "Comentário real número 1" not in prompt             # não reenvia o já incorporado
    assert treino.guia_versao == 2
    assert repo.guia_por_versao("back", 1).conteudo == "# Guia com padrão A"  # versão antiga preservada
    assert repo.guia_ativo("back").exemplos_usados == 2


def test_muitos_comentarios_viram_varios_lotes_e_nenhum_e_descartado(repo):
    gitlab = FakeGitLab(comentarios=[comentario(n) for n in range(1, 31)])
    llm = FakeLLM(*[f"# Guia após lote {i}" for i in range(1, 31)])
    # min_comentarios_guia_micro alto: isola este teste da camada de guia por micro (testada à parte)
    treino = treinar(repo, gitlab, llm, max_caracteres_lote=400, min_comentarios_guia_micro=9999)

    lotes = len(llm.chamadas)
    assert lotes > 1
    assert repo.contar_exemplos_pendentes("back") == 0
    assert repo.guia_ativo("back").exemplos_usados == 30
    assert treino.guia_versao == lotes
    # cada lote recebe o guia produzido pelo lote anterior
    for i in range(1, lotes):
        assert f"# Guia após lote {i}" in llm.chamadas[i][1]
    # todo comentário aparece em exatamente um lote
    for n in range(1, 31):
        assert sum(f"número {n} sobre" in usuario for _, usuario in llm.chamadas) == 1


def test_falha_no_meio_preserva_lotes_ja_incorporados(repo):
    gitlab = FakeGitLab(comentarios=[comentario(n) for n in range(1, 11)])
    llm = FakeLLM("# Guia lote 1")  # só uma resposta: o 2º lote falha
    treino = treinar(repo, gitlab, llm, max_caracteres_lote=400)

    assert treino.status == StatusExecucao.ERRO
    assert repo.guia_ativo("back").conteudo == "# Guia lote 1"
    pendentes = repo.contar_exemplos_pendentes("back")
    assert 0 < pendentes < 10

    llm2 = FakeLLM(*["# Guia completo"] * 10)
    treinar(repo, gitlab, llm2, max_caracteres_lote=400)
    assert repo.contar_exemplos_pendentes("back") == 0
    assert "# Guia lote 1" in llm2.chamadas[0][1]


def test_sem_novidade_nao_chama_llm_nem_cria_versao(repo):
    gitlab = FakeGitLab(comentarios=[comentario(1)])
    treinar(repo, gitlab, FakeLLM("# Guia v1"))
    llm = FakeLLM()
    treino = treinar(repo, gitlab, llm)
    assert llm.chamadas == [] and treino.novos_exemplos == 0
    assert repo.guia_ativo("back").versao == 1


def test_checkpoint_por_projeto_e_projeto_novo_le_historico_inteiro(repo):
    gitlab = FakeGitLab()
    t1 = treinar(repo, gitlab, FakeLLM())
    assert [c[2] for c in gitlab.consultas_comentarios] == ["2025-01-01", "2025-01-01"]

    gitlab.consultas_comentarios.clear()
    uc = TreinarPerfil(gitlab, FakeLLM(), repo, PERFIS, [], ["g/api", "g/novo"], set(), "2025-01-01")
    uc.executar(uc.iniciar("back"))
    desde = dict((p, d) for p, _, d in gitlab.consultas_comentarios)
    assert desde == {"g/api": t1.iniciado_em, "g/novo": "2025-01-01"}


def test_reler_historico_ignora_checkpoint_sem_duplicar(repo):
    gitlab = FakeGitLab(comentarios=[comentario(1)])
    treinar(repo, gitlab, FakeLLM("# Guia"))
    gitlab.consultas_comentarios.clear()
    treino = treinar(repo, gitlab, FakeLLM(), completo=True)
    assert all(d == "2025-01-01" for _, _, d in gitlab.consultas_comentarios)
    assert treino.novos_exemplos == 0 and repo.contar_exemplos("back") == 1


def test_rejeicoes_entram_uma_vez_mesmo_sem_comentarios_novos(repo):
    revisao_id = repo.criar_revisao(Revisao("u", "g/p", 1, "back", status=StatusExecucao.CONCLUIDA))
    ap = Apontamento(revisao_id, "A.java", "A.java", 1, None, Severidade.P2, 5,
                     "Apontamento chato", "trecho")
    repo.adicionar_apontamentos([ap])
    TriarApontamento(repo).rejeitar(ap.id, MotivoRejeicao.IRRELEVANTE)

    llm = FakeLLM("# Guia com o que evitar")
    treinar(repo, FakeGitLab(), llm)
    assert "[IRRELEVANTE]" in llm.chamadas[0][1] and "Apontamento chato" in llm.chamadas[0][1]

    llm2 = FakeLLM()
    treinar(repo, FakeGitLab(), llm2)
    assert llm2.chamadas == []  # já incorporada


def test_falha_no_gitlab_marca_erro_e_nao_avanca_checkpoint(repo):
    class GitLabQuebrado(FakeGitLab):
        def listar_comentarios(self, *a):
            raise ConnectionError("401 Unauthorized")
            yield  # pragma: no cover

    treino = treinar(repo, GitLabQuebrado(), FakeLLM())
    assert treino.status == StatusExecucao.ERRO and "401" in treino.erro
    assert repo.checkpoint("back", "g/api") is None


def test_nao_permite_dois_treinos_simultaneos(repo):
    uc = TreinarPerfil(FakeGitLab(), FakeLLM(), repo, PERFIS, [], ["g/api"], set(), "2025-01-01")
    uc.iniciar("back")
    with pytest.raises(ValueError):
        uc.iniciar("back")


# ---------- R3: guias em camadas (geral + por microserviço) ----------

def test_micro_com_minimo_de_comentarios_ganha_guia_proprio_abaixo_nao(repo):
    comentarios_a = [comentario(n, projeto="g/a") for n in range(1, 31)]   # 30: atinge o mínimo
    comentarios_b = [comentario(n, projeto="g/b") for n in range(100, 110)]  # 10: não atinge
    gitlab = FakeGitLab(comentarios=comentarios_a + comentarios_b)
    llm = FakeLLM("# Guia geral", "# Guia do g/a")
    treinar(repo, gitlab, llm, projetos=["g/a", "g/b"])
    assert repo.guia_ativo("back", "g/a") is not None
    assert repo.guia_ativo("back", "g/b") is None
    assert repo.listar_escopos_guia("back") == ["g/a"]


def test_prompt_do_guia_do_micro_nao_contem_comentarios_de_outro_micro(repo):
    comentarios_a = [comentario(n, projeto="g/a") for n in range(1, 31)]
    comentarios_b = [comentario(n, projeto="g/b", texto="Comentário do projeto b, bem diferente.")
                     for n in range(100, 105)]
    gitlab = FakeGitLab(comentarios=comentarios_a + comentarios_b)
    llm = FakeLLM("# Guia geral", "# Guia do g/a")
    treinar(repo, gitlab, llm, projetos=["g/a", "g/b"])
    _, prompt_micro = llm.chamadas[1]
    assert "setStatus" in prompt_micro
    assert "projeto b" not in prompt_micro


def test_segundo_treino_envia_so_comentarios_novos_para_cada_camada(repo):
    gitlab = FakeGitLab(comentarios=[comentario(n, projeto="g/a") for n in range(1, 31)])
    llm1 = FakeLLM("# Guia geral v1", "# Guia do g/a v1")
    treinar(repo, gitlab, llm1, projetos=["g/a"])

    gitlab.comentarios.append(
        comentario(31, projeto="g/a", texto="Comentário real número 31 sobre setStatus.")
    )
    llm2 = FakeLLM("# Guia geral v2", "# Guia do g/a v2")
    treinar(repo, gitlab, llm2, projetos=["g/a"])
    _, geral_prompt = llm2.chamadas[0]
    _, micro_prompt = llm2.chamadas[1]
    assert "número 31" in geral_prompt and "número 1 " not in geral_prompt
    assert "número 31" in micro_prompt and "número 1 " not in micro_prompt


# ---------- R4: mapa técnico do código ----------

def test_mapeia_projetos_descobertos_quando_tem_arquivo_do_perfil(repo):
    caminho_service = "src/main/java/com/x/ContratoService.java"
    arvore = ArvoreProjeto(sha="sha1", caminhos=(caminho_service, "README.md"))
    gitlab = FakeGitLab(
        arvores={"g/api": arvore},
        conteudos_arquivo={("g/api", caminho_service, "sha1"): "class ContratoService {}",
                           ("g/api", "README.md", "sha1"): "# A"},
    )
    treino = treinar(repo, gitlab, FakeLLM("# Mapa técnico de g/api"), projetos=["g/api"])
    assert treino.status == StatusExecucao.CONCLUIDA
    mapa = repo.mapa_ativo("g/api")
    assert mapa is not None and mapa.conteudo == "# Mapa técnico de g/api"
    assert mapa.sha == "sha1"
    assert set(mapa.arquivos_lidos) == {caminho_service, "README.md"}


def test_mapa_recente_nao_e_refeito(repo):
    arvore = ArvoreProjeto(sha="sha1", caminhos=("src/A.java",))
    gitlab = FakeGitLab(arvores={"g/api": arvore},
                        conteudos_arquivo={("g/api", "src/A.java", "sha1"): "class A {}"})
    relogio1 = lambda: datetime(2025, 1, 10, tzinfo=timezone.utc)
    treinar(repo, gitlab, FakeLLM("# Mapa"), projetos=["g/api"], relogio=relogio1)
    assert repo.mapa_ativo("g/api").sha == "sha1"

    relogio2 = lambda: datetime(2025, 1, 15, tzinfo=timezone.utc)  # 5 dias depois: ainda válido
    llm2 = FakeLLM()
    treinar(repo, gitlab, llm2, projetos=["g/api"], relogio=relogio2)
    assert llm2.chamadas == []


def test_mapa_vencido_e_refeito_mas_com_sha_igual_nao_chama_llm(repo):
    arvore = ArvoreProjeto(sha="sha1", caminhos=("src/A.java",))
    gitlab = FakeGitLab(arvores={"g/api": arvore},
                        conteudos_arquivo={("g/api", "src/A.java", "sha1"): "class A {}"})
    relogio1 = lambda: datetime(2025, 1, 1, tzinfo=timezone.utc)
    treinar(repo, gitlab, FakeLLM("# Mapa v1"), projetos=["g/api"], relogio=relogio1,
            mapa_validade_dias=30)

    relogio2 = lambda: datetime(2025, 2, 10, tzinfo=timezone.utc)  # 40 dias: vencido, mas SHA igual
    llm2 = FakeLLM()
    treinar(repo, gitlab, llm2, projetos=["g/api"], relogio=relogio2, mapa_validade_dias=30)
    assert llm2.chamadas == []
    assert repo.mapa_ativo("g/api").conteudo == "# Mapa v1"

    gitlab.arvores["g/api"] = ArvoreProjeto(sha="sha2", caminhos=("src/A.java",))
    gitlab.conteudos_arquivo[("g/api", "src/A.java", "sha2")] = "class A { void x(){} }"
    llm3 = FakeLLM("# Mapa v2")
    treinar(repo, gitlab, llm3, projetos=["g/api"], relogio=relogio2, mapa_validade_dias=30)
    assert len(llm3.chamadas) == 1
    assert repo.mapa_ativo("g/api").sha == "sha2"


def test_projeto_sem_arquivo_do_perfil_nao_e_mapeado(repo):
    arvore = ArvoreProjeto(sha="sha1", caminhos=("app.component.ts",))  # só front
    gitlab = FakeGitLab(arvores={"g/front": arvore})
    llm = FakeLLM()
    treinar(repo, gitlab, llm, perfil="back", projetos=["g/front"])
    assert repo.mapa_ativo("g/front") is None
    assert llm.chamadas == []


# ---------- resumo de arquitetura (ADRs) ----------

def test_resumo_de_arquitetura_e_gerado_quando_configurado(repo):
    arvore_adr = ArvoreProjeto(sha="sha1", caminhos=("docs/adr/0001-x.md", "README.md"))
    gitlab = FakeGitLab(
        arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",)), "attus/workspace": arvore_adr},
        conteudos_arquivo={("attus/workspace", "docs/adr/0001-x.md", "sha1"): "# ADR 1\nDecisão: usar Postgres"},
    )
    treino = treinar(repo, gitlab, FakeLLM("Resumo das ADRs"), projetos=["g/api"],
                     adr_projeto="attus/workspace")
    assert treino.status == StatusExecucao.CONCLUIDA
    guia = repo.guia_arquitetura_ativo()
    assert guia is not None
    assert guia.conteudo == "Resumo das ADRs"
    assert guia.sha == "sha1"
    assert guia.arquivos_lidos == ("docs/adr/0001-x.md",)


def test_adr_projeto_vazio_nunca_chama_obter_arvore(repo):
    gitlab = FakeGitLab(arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",))})
    treino = treinar(repo, gitlab, FakeLLM(), projetos=["g/api"])  # adr_projeto não configurado
    assert treino.status == StatusExecucao.CONCLUIDA
    assert repo.guia_arquitetura_ativo() is None
    assert "ADRs" not in treino.avisos


def test_resumo_de_arquitetura_recente_nao_e_refeito(repo):
    arvore_adr = ArvoreProjeto(sha="sha1", caminhos=("docs/adr/0001-x.md",))
    gitlab = FakeGitLab(
        arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",)), "attus/workspace": arvore_adr},
        conteudos_arquivo={("attus/workspace", "docs/adr/0001-x.md", "sha1"): "# ADR 1"},
    )
    relogio1 = lambda: datetime(2025, 1, 10, tzinfo=timezone.utc)
    treinar(repo, gitlab, FakeLLM("Resumo v1"), projetos=["g/api"], adr_projeto="attus/workspace",
            relogio=relogio1)
    assert repo.guia_arquitetura_ativo().sha == "sha1"

    relogio2 = lambda: datetime(2025, 1, 15, tzinfo=timezone.utc)  # 5 dias depois: ainda válido
    llm2 = FakeLLM()
    treinar(repo, gitlab, llm2, projetos=["g/api"], adr_projeto="attus/workspace", relogio=relogio2)
    assert llm2.chamadas == []


def test_resumo_de_arquitetura_vencido_mas_sha_igual_nao_chama_llm(repo):
    arvore_adr = ArvoreProjeto(sha="sha1", caminhos=("docs/adr/0001-x.md",))
    gitlab = FakeGitLab(
        arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",)), "attus/workspace": arvore_adr},
        conteudos_arquivo={("attus/workspace", "docs/adr/0001-x.md", "sha1"): "# ADR 1"},
    )
    relogio1 = lambda: datetime(2025, 1, 1, tzinfo=timezone.utc)
    treinar(repo, gitlab, FakeLLM("Resumo v1"), projetos=["g/api"], adr_projeto="attus/workspace",
            relogio=relogio1, adr_validade_dias=30)

    relogio2 = lambda: datetime(2025, 2, 10, tzinfo=timezone.utc)  # 40 dias: vencido, mas SHA igual
    llm2 = FakeLLM()
    treinar(repo, gitlab, llm2, projetos=["g/api"], adr_projeto="attus/workspace", relogio=relogio2,
            adr_validade_dias=30)
    assert llm2.chamadas == []
    assert repo.guia_arquitetura_ativo().conteudo == "Resumo v1"


def test_nenhuma_adr_encontrada_registra_aviso_sem_quebrar(repo):
    gitlab = FakeGitLab(
        arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",)),
                "attus/workspace": ArvoreProjeto(sha="sha1", caminhos=("README.md",))},
    )
    treino = treinar(repo, gitlab, FakeLLM(), projetos=["g/api"], adr_projeto="attus/workspace")
    assert treino.status == StatusExecucao.CONCLUIDA
    assert repo.guia_arquitetura_ativo() is None
    assert "attus/workspace" in treino.avisos


def test_falha_ao_atualizar_adr_vira_aviso_sem_quebrar_treino(repo):
    gitlab = FakeGitLab(
        arvores={"g/api": ArvoreProjeto(sha="sha1", caminhos=("README.md",))},
        falhar_arvore={"attus/workspace"},
    )
    treino = treinar(repo, gitlab, FakeLLM(), projetos=["g/api"], adr_projeto="attus/workspace")
    assert treino.status == StatusExecucao.CONCLUIDA
    assert "attus/workspace" in treino.avisos
    assert repo.guia_arquitetura_ativo() is None


def test_falha_ao_mapear_vira_aviso(repo):
    gitlab = FakeGitLab(falhar_arvore={"g/quebrado"})
    treino = treinar(repo, gitlab, FakeLLM(), projetos=["g/quebrado"])
    assert treino.status == StatusExecucao.CONCLUIDA
    assert "g/quebrado" in treino.avisos
    assert repo.mapa_ativo("g/quebrado") is None
