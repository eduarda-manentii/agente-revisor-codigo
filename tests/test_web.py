"""Fluxo ponta a ponta pela interface, com GitLab e LLM falsos."""
import json
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
        limite_inatividade_segundos=60,
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


# ---------- progresso: etapa, cronômetro, histórico, cancelar/reiniciar ----------

def test_tela_de_revisao_concluida_mostra_duracao_e_historico(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    revisao_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))
    assert "decorrido" in resposta.text
    assert "Histórico (" in resposta.text
    assert "Carregando diff do MR..." in resposta.text


def test_eventos_sse_responde_text_event_stream_com_payload_valido(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    revisao_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))

    with cliente.stream("GET", f"/revisoes/{revisao_id}/eventos") as stream:
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        linha = next(l for l in stream.iter_lines() if l.startswith("data: "))
        payload = json.loads(linha[len("data: "):])
    assert payload["status"] == "CONCLUIDA"
    assert "travado" in payload and payload["travado"] is False


def test_cancelar_muda_status_de_revisao_em_andamento(ambiente):
    cliente, repo, _ = ambiente
    revisao_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 9, "back", status=StatusExecucao.PROCESSANDO))
    resposta = cliente.post(f"/revisoes/{revisao_id}/cancelar")
    assert "Revisão cancelada" in resposta.text
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CANCELADA


def test_cancelar_revisao_ja_terminal_e_rejeitado(ambiente):
    cliente, repo, _ = ambiente
    revisao_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 9, "back", status=StatusExecucao.CONCLUIDA))
    resposta = cliente.post(f"/revisoes/{revisao_id}/cancelar")
    assert "Não é possível ir de" in resposta.text
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CONCLUIDA


def test_reiniciar_cria_nova_revisao_para_o_mesmo_mr(ambiente):
    cliente, repo, _ = ambiente
    revisao_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 9, "back", status=StatusExecucao.PROCESSANDO))
    resposta = cliente.post(f"/revisoes/{revisao_id}/reiniciar")
    nova_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))
    assert nova_id != revisao_id
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CANCELADA
    nova = repo.obter_revisao(nova_id)
    assert nova.mr_url == URL_MR and nova.status == StatusExecucao.CONCLUIDA  # já rodou (background síncrono no teste)


def test_tela_de_revisao_mostra_prontidao_sem_review_anterior(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    assert "Prontidão:" in resposta.text
    assert "Comparado com o" not in resposta.text


def test_tela_de_revisao_mostra_comparacao_com_review_anterior_do_mesmo_mr(repo):
    gitlab = FakeGitLab()
    anterior_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 3, "back", status=StatusExecucao.CONCLUIDA))
    repo.adicionar_apontamentos([
        Apontamento(anterior_id, "X.java", "X.java", 12, None, Severidade.P1, 8, "Problema antigo", "t")
    ])
    llm = FakeLLM([sugestao(linha=12, comentario="Status do request")])
    cliente = TestClient(criar_app(servicos(repo, gitlab, llm)))

    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    assert "Comparado com o" in resposta.text
    assert "1 resolvido(s) · 0 repetido(s) · 1 novo(s)" in resposta.text


def test_prontidao_nao_aparece_quando_revisao_falha(repo):
    revisao_id = repo.criar_revisao(Revisao(URL_MR, "g/api", 3, "back", status=StatusExecucao.ERRO))
    cliente = TestClient(criar_app(servicos(repo, FakeGitLab(), FakeLLM())))
    resposta = cliente.get(f"/revisoes/{revisao_id}")
    assert "Prontidão:" not in resposta.text


def test_reload_da_pagina_mantem_a_mesma_etapa_persistida(ambiente):
    cliente, repo, _ = ambiente
    resposta = cliente.post("/revisoes", data={"url": URL_MR, "perfil": "back"})
    revisao_id = int(re.search(r"/revisoes/(\d+)", str(resposta.url)).group(1))
    primeira = cliente.get(f"/revisoes/{revisao_id}").text
    segunda = cliente.get(f"/revisoes/{revisao_id}").text
    etapa = repo.obter_revisao(revisao_id).etapa
    assert etapa in primeira and etapa in segunda
