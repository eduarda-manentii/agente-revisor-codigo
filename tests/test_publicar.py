from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade, Status
from revisor.dominio.modelos import Revisao, StatusExecucao
from tests.fakes import FakeGitLab, sugestao


def preparar(repo, gitlab, sugestoes):
    """Cria a revisão e os apontamentos direto no banco, como o pipeline de agentes+coordenador
    (v3) teria produzido — estes testes só verificam a publicação, não como os apontamentos surgem."""
    mr = gitlab.mr
    revisao_id = repo.criar_revisao(Revisao(
        mr_url="https://gitlab.empresa.com/g/p/-/merge_requests/1", projeto="g/p", mr_iid=1,
        perfil="back", status=StatusExecucao.CONCLUIDA,
        base_sha=mr.base_sha, start_sha=mr.start_sha, head_sha=mr.head_sha,
    ))
    apontamentos = []
    for s in sugestoes:
        arquivo = next(a for a in mr.arquivos if a.caminho_novo == s["arquivo"])
        linha_obj = arquivo.linha(s["linha"])
        apontamentos.append(Apontamento(
            revisao_id=revisao_id, arquivo=arquivo.caminho_novo, caminho_antigo=arquivo.caminho_antigo,
            linha=s["linha"], linha_antiga=linha_obj.linha_antiga if linha_obj.tipo == " " else None,
            severidade=Severidade(s["severidade"]), confianca=s["confianca"],
            texto_original=s["comentario"], trecho=arquivo.trecho(s["linha"]),
        ))
    repo.adicionar_apontamentos(apontamentos)
    return revisao_id, apontamentos


def test_publica_so_aprovados_com_texto_editado_e_posicao_correta(repo):
    gitlab = FakeGitLab()
    revisao_id, aps = preparar(repo, gitlab, [sugestao(linha=12, comentario="A"),
                                              sugestao(linha=14, comentario="B"),
                                              sugestao(linha=13, comentario="C")])
    triar = TriarApontamento(repo)
    por_linha = {a.linha: a for a in aps}
    triar.aprovar(por_linha[12].id, "A editado")
    triar.aprovar(por_linha[14].id)
    triar.rejeitar(por_linha[13].id, MotivoRejeicao.FALSO_POSITIVO)

    resultado = PublicarAprovados(gitlab, repo).executar(revisao_id)

    assert resultado.publicados == 2
    corpos = {p.linha_nova: corpo for p, corpo in gitlab.publicados}
    assert corpos == {12: "A editado", 14: "B"}
    posicoes = {p.linha_nova: p for p, _ in gitlab.publicados}
    assert posicoes[12].linha_antiga is None
    assert posicoes[14].linha_antiga == 12
    assert (posicoes[12].base_sha, posicoes[12].start_sha, posicoes[12].head_sha) == ("b1", "s1", "h1")


def test_publicar_duas_vezes_nao_duplica(repo):
    gitlab = FakeGitLab()
    revisao_id, aps = preparar(repo, gitlab, [sugestao()])
    TriarApontamento(repo).aprovar(aps[0].id)
    publicar = PublicarAprovados(gitlab, repo)
    publicar.executar(revisao_id)
    segundo = publicar.executar(revisao_id)
    assert segundo.publicados == 0
    assert len(gitlab.publicados) == 1
    assert repo.obter_apontamento(aps[0].id).discussion_id == "disc-1"


def test_mr_com_commit_novo_marca_desatualizado_sem_publicar(repo):
    gitlab = FakeGitLab()
    revisao_id, aps = preparar(repo, gitlab, [sugestao()])
    TriarApontamento(repo).aprovar(aps[0].id)
    gitlab.head_atual = "h2"
    resultado = PublicarAprovados(gitlab, repo).executar(revisao_id)
    assert resultado.desatualizados == 1
    assert gitlab.publicados == []
    assert repo.obter_apontamento(aps[0].id).status == Status.DESATUALIZADO


def test_falha_parcial_isola_erro_e_permite_retry(repo):
    gitlab = FakeGitLab(falhar_em={12})
    revisao_id, aps = preparar(repo, gitlab, [sugestao(linha=12), sugestao(linha=13, comentario="outro")])
    for ap in aps:
        TriarApontamento(repo).aprovar(ap.id)
    publicar = PublicarAprovados(gitlab, repo)

    r1 = publicar.executar(revisao_id)
    assert (r1.publicados, r1.falhas) == (1, 1)
    falho = next(a for a in repo.listar_apontamentos(revisao_id) if a.linha == 12)
    assert falho.status == Status.FALHA_PUBLICACAO and "400" in falho.erro

    gitlab.falhar_em.clear()
    r2 = publicar.executar(revisao_id)
    assert (r2.publicados, r2.falhas) == (1, 0)
    assert len(gitlab.publicados) == 2


def test_nada_aprovado_nao_consulta_gitlab(repo):
    gitlab = FakeGitLab()
    revisao_id, _ = preparar(repo, gitlab, [sugestao()])
    gitlab.head_atual = "qualquer"  # se consultasse, marcaria desatualizado
    assert PublicarAprovados(gitlab, repo).executar(revisao_id).publicados == 0
    assert repo.listar_apontamentos(revisao_id)[0].status == Status.PENDENTE
