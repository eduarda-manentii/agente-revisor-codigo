"""Fluxo ponta a ponta pela interface, com GitLab e LLM falsos."""
import re

import pytest
from fastapi.testclient import TestClient

from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.dominio.apontamento import Apontamento, Severidade, Status
from revisor.dominio.modelos import GERAL, Exemplo, Revisao, StatusExecucao
from revisor.web.app import Servicos, criar_app
from tests.fakes import PERFIS, FakeGitLab, FakeLLM, sugestao

URL_MR = "https://gitlab.empresa.com/g/api/-/merge_requests/3"


def servicos(repo, gitlab, llm) -> Servicos:
    return Servicos(
        repo=repo, perfis=PERFIS, gitlab_url="https://gitlab.empresa.com",
        revisar=RevisarMR(gitlab, llm, repo, PERFIS, "gitlab.empresa.com"),
        triar=TriarApontamento(repo),
        publicar=PublicarAprovados(gitlab, repo),
        treinar=TreinarPerfil(gitlab, FakeLLM(), repo, PERFIS, [], ["g/api"], set(), "2025-01-01"),
    )


@pytest.fixture
def ambiente(repo):
    gitlab = FakeGitLab()
    llm = FakeLLM([sugestao(linha=12, comentario="Status do request"), sugestao(linha=13, comentario="Outro")])
    s = servicos(repo, gitlab, llm)
    return TestClient(criar_app(s)), repo, gitlab


def test_inicio_renderiza_perfis(ambiente):
    cliente, _, _ = ambiente
    html = cliente.get("/").text
    assert "Revisar MR" in html and "back" in html and "front" in html


def test_fluxo_revisar_triar_publicar(ambiente):
    cliente, repo, gitlab = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    assert resposta.status_code == 200  # seguiu o redirect; a tarefa em background já rodou
    revisao_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))
    assert "Status do request" in resposta.text

    aps = {a.linha: a for a in repo.listar_apontamentos(revisao_id)}
    cliente.post(f"/revisoes/{revisao_id}/apontamentos/{aps[12].id}/aprovar", data={"texto": "Editado"})
    cliente.post(f"/revisoes/{revisao_id}/apontamentos/{aps[13].id}/rejeitar", data={"motivo": "TOM"})

    resposta = cliente.post(f"/revisoes/{revisao_id}/publicar")
    assert "1 comentário(s) publicado(s)" in resposta.text
    assert [corpo for _, corpo in gitlab.publicados] == ["Editado"]
    assert repo.obter_apontamento(aps[13].id).status == Status.REJEITADO


def test_link_invalido_volta_com_erro(ambiente):
    cliente, _, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": "https://outro.com/x/-/merge_requests/1", "perfil": "back"})
    assert "GitLab configurado" in resposta.text


def test_transicao_invalida_mostra_erro(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    revisao_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))
    ap = repo.listar_apontamentos(revisao_id)[0]
    resposta = cliente.post(f"/revisoes/{revisao_id}/apontamentos/{ap.id}/aprovar", data={"texto": "  "})
    assert "não pode ficar vazio" in resposta.text


def test_treinar_pela_tela(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/perfis/back/treinar")
    assert "Treino do perfil back iniciado" in resposta.text
    assert repo.ultimo_treino("back").status == "CONCLUIDA"
    assert "Ainda não há guia" in cliente.get("/perfis/back/guia").text  # sem comentários, sem guia


def test_pagina_de_mapas_responde_200(ambiente):
    cliente, _, _ = ambiente
    resposta = cliente.get("/mapas")
    assert resposta.status_code == 200
    assert "mapeado" in resposta.text.lower()


def test_pagina_de_guia_com_abas_e_escopo_de_micro_responde_200(ambiente):
    cliente, repo, _ = ambiente
    repo.salvar_guia("back", GERAL, "GUIA GERAL AQUI", [], [])
    repo.salvar_guia("back", "g/api", "GUIA DO MICRO AQUI", [], [])
    geral = cliente.get("/perfis/back/guia")
    assert geral.status_code == 200 and "GUIA GERAL AQUI" in geral.text and "g/api" in geral.text
    micro = cliente.get("/perfis/back/guia?escopo=g/api")
    assert micro.status_code == 200 and "GUIA DO MICRO AQUI" in micro.text


def test_revisao_mostra_motivo_fonte_confirmada_com_link_e_selo_sem_precedente(repo):
    repo.salvar_exemplo(Exemplo("back", "g/api", 1, 77, "X.java", 1, "trecho antigo",
                                "Nunca aceite status do request.", True, autor="fulana",
                                criado_em="2025-06-01T00:00:00Z"))
    gitlab = FakeGitLab()
    llm = FakeLLM([
        sugestao(linha=12, comentario="Com fonte", motivo="por isso é um problema concreto",
                 fontes={"comentarios": [77], "padrao_guia": "", "regra_perfil": ""}),
        sugestao(linha=13, comentario="Sem fonte nenhuma"),
    ])
    cliente = TestClient(criar_app(servicos(repo, gitlab, llm)))

    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    assert "por isso é um problema concreto" in resposta.text
    assert "#note_77" in resposta.text
    assert "fulana" in resposta.text
    assert "Sem precedente na equipe" in resposta.text


def test_apontamento_antigo_sem_fontes_mostra_aviso_de_versao_anterior(repo):
    revisao_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 3, "back", status=StatusExecucao.CONCLUIDA))
    repo.adicionar_apontamentos([
        Apontamento(revisao_id, "X.java", "X.java", 1, None, Severidade.P2, 6, "texto", "trecho")
    ])
    gitlab = FakeGitLab()
    cliente = TestClient(criar_app(servicos(repo, gitlab, FakeLLM())))

    resposta = cliente.get(f"/revisoes/{revisao_id}")
    assert "Reviews feitos antes desta versão não têm essa informação" in resposta.text
    assert "Sem precedente na equipe" not in resposta.text
