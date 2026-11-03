import pytest

from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import TriarApontamento
from revisor.dominio.apontamento import MotivoRejeicao
from revisor.dominio.modelos import ComentarioHistorico, StatusExecucao
from tests.fakes import PERFIS, FakeGitLab, FakeLLM, sugestao


def comentario(note_id, arquivo="src/A.java", texto=None, projeto="g/api"):
    texto = texto or f"Comentário real número {note_id} sobre setStatus."
    return ComentarioHistorico(projeto, 1, note_id, arquivo, 10, texto, True, "trecho setStatus")


def treinar(repo, gitlab, llm, perfil="back", completo=False, **kw):
    uc = TreinarPerfil(gitlab, llm, repo, PERFIS, "fulana", ["g/api", "g/web"], "2025-01-01", **kw)
    treino_id = uc.iniciar(perfil, completo=completo)
    uc.executar(treino_id)
    return repo.obter_treino(treino_id)


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
    treino = treinar(repo, gitlab, llm, max_caracteres_lote=400)

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
    uc = TreinarPerfil(gitlab, FakeLLM(), repo, PERFIS, "fulana", ["g/api", "g/novo"], "2025-01-01")
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
    uc = RevisarMR(FakeGitLab(), FakeLLM([sugestao(comentario="Apontamento chato")]), repo, PERFIS,
                   "gitlab.empresa.com")
    revisao_id = uc.iniciar("https://gitlab.empresa.com/g/p/-/merge_requests/1", "back")
    uc.executar(revisao_id)
    TriarApontamento(repo).rejeitar(repo.listar_apontamentos(revisao_id)[0].id, MotivoRejeicao.IRRELEVANTE)

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
    uc = TreinarPerfil(FakeGitLab(), FakeLLM(), repo, PERFIS, "fulana", ["g/api"], "2025-01-01")
    uc.iniciar("back")
    with pytest.raises(ValueError):
        uc.iniciar("back")
