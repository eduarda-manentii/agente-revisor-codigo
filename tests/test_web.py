"""Fluxo ponta a ponta pela interface, com GitLab e LLM falsos."""
import re

import pytest
from fastapi.testclient import TestClient

from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.dominio.apontamento import Status
from revisor.web.app import Servicos, criar_app
from tests.fakes import PERFIS, FakeGitLab, FakeLLM, sugestao

URL_MR = "https://gitlab.empresa.com/g/api/-/merge_requests/3"


@pytest.fixture
def ambiente(repo):
    gitlab = FakeGitLab()
    llm = FakeLLM([sugestao(linha=12, comentario="Status do request"), sugestao(linha=13, comentario="Outro")])
    s = Servicos(
        repo=repo, perfis=PERFIS,
        revisar=RevisarMR(gitlab, llm, repo, PERFIS, "gitlab.empresa.com"),
        triar=TriarApontamento(repo),
        publicar=PublicarAprovados(gitlab, repo),
        treinar=TreinarPerfil(gitlab, FakeLLM(), repo, PERFIS, "fulana", ["g/api"], "2025-01-01"),
    )
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
