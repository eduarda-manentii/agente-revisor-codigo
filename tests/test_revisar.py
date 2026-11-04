import pytest

from revisor.aplicacao.executar_agentes import ExecutarAgentes
from revisor.aplicacao.revisar import RevisarMR
from revisor.dominio.agentes import ResultadoAgente
from revisor.dominio.apontamento import Severidade
from revisor.dominio.modelos import GERAL, Exemplo, StatusExecucao
from tests.fakes import (AGENTES, DIFF_COMPONENTE, DIFF_SERVICE, PERFIS, FakeCoordenador, FakeGitLab,
                         FakePortaAgente, FakeWorkspace, achado, arquivo, dados_mr)

URL = "https://gitlab.empresa.com/grupo/api/-/merge_requests/7"


def caso(repo, gitlab=None, workspace=None, agente=None, coordenador=None, agentes=None, **kw):
    gitlab = gitlab or FakeGitLab()
    workspace = workspace if workspace is not None else FakeWorkspace()
    agente = agente if agente is not None else FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", achados=(achado(),), modelo_usado="sonnet"),
    })
    coordenador = coordenador if coordenador is not None else FakeCoordenador()
    executar_agentes = ExecutarAgentes(agente, repo, agentes or AGENTES, **kw)
    uc = RevisarMR(gitlab, repo, PERFIS, "gitlab.empresa.com", workspace, executar_agentes, coordenador)
    return uc, gitlab, agente, coordenador


def rodar(uc, repo, perfil="back"):
    revisao_id = uc.iniciar(URL, perfil)
    uc.executar(revisao_id)
    return repo.obter_revisao(revisao_id), repo.listar_apontamentos(revisao_id)


# ---------- fluxo feliz: agentes -> pré-consolidação -> coordenador -> apontamento ----------

def test_gera_apontamento_com_origens_trecho_e_shas(repo):
    uc, _, _, _ = caso(repo)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert (revisao.base_sha, revisao.start_sha, revisao.head_sha) == ("b1", "s1", "h1")
    assert len(aps) == 1
    assert aps[0].linha == 12 and aps[0].linha_antiga is None  # linha adicionada
    assert ">   12 +" in aps[0].trecho
    assert aps[0].origens == "qualidade"
    assert aps[0].texto_original == "Reescrito pelo coordenador (grupo 1)"  # tom do coordenador, não do agente


def test_linha_de_contexto_guarda_linha_antiga(repo):
    ag = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", achados=(achado(linha=14),)),
    })
    uc, _, _, _ = caso(repo, agente=ag)
    _, aps = rodar(uc, repo)
    assert aps[0].linha_antiga == 12


def test_achado_em_linha_fora_do_diff_vira_descarte_em_vez_de_apontamento(repo):
    ag = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", achados=(achado(linha=999),)),
    })
    uc, _, _, _ = caso(repo, agente=ag)
    revisao, aps = rodar(uc, repo)
    assert aps == []
    descartados = repo.listar_descartes(revisao.id)
    assert len(descartados) == 1
    assert descartados[0].motivo == "Linha fora do diff."


def test_filtra_arquivos_pelo_perfil(repo):
    mr = dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE), arquivo("lista.component.ts", DIFF_COMPONENTE))
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), agente=ag)
    rodar(uc, repo, perfil="front")
    assert ag.chamadas == ["qualidade"]  # agente rodou, mas só pros arquivos do perfil front


def test_sem_arquivos_do_perfil_nao_roda_agente(repo):
    mr = dados_mr(arquivo("lista.component.ts", DIFF_COMPONENTE))
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), agente=ag)
    revisao, _ = rodar(uc, repo, perfil="back")
    assert ag.chamadas == []
    assert revisao.status == StatusExecucao.CONCLUIDA and "Nenhum arquivo" in revisao.nota


def test_arquivo_removido_e_ignorado(repo):
    mr = dados_mr(arquivo("Velho.java", DIFF_SERVICE, removido=True))
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), agente=ag)
    rodar(uc, repo)
    assert ag.chamadas == []


@pytest.mark.parametrize("url,perfil", [
    ("https://outro.gitlab.com/g/p/-/merge_requests/1", "back"),
    (URL, "inexistente"),
    ("não é url", "back"),
])
def test_iniciar_valida_entrada(repo, url, perfil):
    uc, _, _, _ = caso(repo)
    with pytest.raises(ValueError):
        uc.iniciar(url, perfil)


# ---------- R3: agentes especialistas ----------

def test_agente_falho_nao_derruba_o_review_e_fica_registrado_no_historico(repo):
    ag = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", erro="deu ruim"),
    })
    uc, _, _, _ = caso(repo, agente=ag)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert aps == []
    assert "Nenhum achado" in revisao.nota and "1 agente(s) falharam" in revisao.nota
    eventos = [e.etapa for e in repo.listar_eventos(revisao.id)]
    assert any("Agente qualidade falhou: deu ruim" in e for e in eventos)


def test_estilo_revisor_recebe_guia_e_exemplos(repo):
    from dataclasses import replace
    from revisor.dominio.modelos import Agente
    repo.salvar_guia("back", GERAL, "GUIA: cobrar status do contexto", [], [])
    repo.salvar_exemplo(Exemplo("back", "p", 1, 99, "X.java", 5, "pedido.setStatus(request.getStatus())",
                                "Nunca aceite status do request.", True))
    ag = FakePortaAgente(respostas={
        "estilo-revisor": ResultadoAgente(agente="estilo-revisor", achados=(achado(categoria="estilo-revisor"),)),
    })
    agentes = {**AGENTES, "estilo-revisor": Agente(nome="estilo-revisor", instrucoes="instr")}
    perfis = {**PERFIS, "back": replace(PERFIS["back"], agentes_por_risco={"TRIVIAL": ("estilo-revisor",)})}
    uc, _, _, _ = caso(repo, agente=ag, agentes=agentes)
    uc._perfis = perfis
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert len(aps) == 1
    usuario = ag.usuarios["estilo-revisor"]
    assert "GUIA: cobrar status do contexto" in usuario
    assert "Nunca aceite status do request." in usuario


# ---------- R4: coordenador ----------

def test_coordenador_recebe_grupos_com_guia_geral_e_micro(repo):
    repo.salvar_guia("back", GERAL, "GUIA GERAL", [], [])
    repo.salvar_guia("back", "grupo/api", "GUIA DO MICRO grupo/api", [], [])
    repo.salvar_guia("back", "grupo/outro", "GUIA DE OUTRO MICRO", [], [])
    coord = FakeCoordenador()
    uc, _, _, _ = caso(repo, coordenador=coord)
    revisao, _ = rodar(uc, repo)
    _, usuario = coord.chamadas[0]
    assert "GUIA GERAL" in usuario
    assert "GUIA DO MICRO grupo/api" in usuario
    assert "GUIA DE OUTRO MICRO" not in usuario
    assert revisao.guia_versao == 1 and revisao.guia_micro_versao == 1


def test_coordenador_falho_cai_no_fallback_com_achados_originais(repo):
    ag = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", achados=(achado(severidade="P0", confianca=9),)),
    })
    coord = FakeCoordenador(excecao=RuntimeError("Claude Code falhou"))
    uc, _, _, _ = caso(repo, agente=ag, coordenador=coord)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert "Consolidação indisponível" in revisao.nota
    assert len(aps) == 1
    assert aps[0].severidade == Severidade.P0  # severidade do próprio achado, sem coordenador
    assert aps[0].origens == "qualidade"


def test_json_invalido_do_coordenador_cai_no_fallback(repo):
    coord = FakeCoordenador(resposta="isso não é json nenhum")
    uc, _, _, _ = caso(repo, coordenador=coord)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert "Consolidação indisponível" in revisao.nota
    assert len(aps) == 1  # fallback: o achado original vira apontamento


def test_grupo_nao_mencionado_pelo_coordenador_vira_descarte(repo):
    ag = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", achados=(achado(),)),
    })
    coord = FakeCoordenador(resposta='{"apontamentos": [], "descartados": [], "resumo": "nada"}')
    uc, _, _, _ = caso(repo, agente=ag, coordenador=coord)
    revisao, aps = rodar(uc, repo)
    assert aps == []
    descartados = repo.listar_descartes(revisao.id)
    assert len(descartados) == 1
    assert descartados[0].motivo == "Não mencionado pelo coordenador."


def test_limite_de_apontamentos_do_perfil_move_excedente_para_descartados(repo):
    diff_grande = "@@ -1,1 +1,50 @@\n" + "\n".join(f"+linha {i}" for i in range(1, 51)) + "\n"
    mr = dados_mr(arquivo("src/ContratoService.java", diff_grande))
    # Linhas espaçadas de 4 em 4: nunca ficam a 3 linhas ou menos uma da outra, então a
    # pré-consolidação nunca agrupa nenhuma com a outra (12 grupos distintos garantidos).
    achados = tuple(achado(linha=1 + i * 4, confianca=i, comentario=f"problema {i}") for i in range(12))
    ag = FakePortaAgente(respostas={"qualidade": ResultadoAgente(agente="qualidade", achados=achados)})
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), agente=ag)
    revisao, aps = rodar(uc, repo)
    assert len(aps) == 10  # max_apontamentos do PERFIL_BACK (dos testes)
    descartados = repo.listar_descartes(revisao.id)
    assert len(descartados) == 2
    assert all(d.motivo == "Excedeu o limite de apontamentos do perfil." for d in descartados)


def test_nenhum_achado_dos_agentes_conclui_sem_chamar_coordenador(repo):
    ag = FakePortaAgente(respostas={"qualidade": ResultadoAgente(agente="qualidade")})
    coord = FakeCoordenador()
    uc, _, _, _ = caso(repo, agente=ag, coordenador=coord)
    revisao, aps = rodar(uc, repo)
    assert aps == []
    assert "Nenhum achado dos agentes" in revisao.nota
    assert coord.chamadas == []


# ---------- progresso, cancelamento e workspace (R1/R6, já existente, adaptado ao pipeline novo) ----------

def test_revisao_nasce_pendente_antes_de_executar(repo):
    uc, _, _, _ = caso(repo)
    revisao_id = uc.iniciar(URL, "back")
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.PENDENTE


def test_etapas_principais_aparecem_no_historico(repo):
    uc, _, _, _ = caso(repo)
    revisao, _ = rodar(uc, repo)
    etapas = [e.etapa for e in repo.listar_eventos(revisao.id)]
    assert "Carregando diff do MR..." in etapas
    assert "Consultando o guia de padrões..." in etapas
    assert any(e.startswith("Agentes especialistas trabalhando") for e in etapas)
    assert "Coordenador consolidando..." in etapas


def test_cancelamento_antes_dos_agentes_nao_gera_apontamentos(repo):
    class AgenteQueNuncaDeveriaRodar:
        def executar(self, agente, workspace, modelo, usuario, ao_progresso):
            raise AssertionError("não deveria ter chamado o agente")

    uc, _, _, _ = caso(repo, agente=AgenteQueNuncaDeveriaRodar())
    revisao_id = uc.iniciar(URL, "back")
    revisao = repo.obter_revisao(revisao_id)
    revisao.status = StatusExecucao.CANCELADA
    repo.salvar_revisao(revisao)

    uc.executar(revisao_id)
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CANCELADA
    assert repo.listar_apontamentos(revisao_id) == []


def test_workspace_e_descartado_mesmo_quando_o_coordenador_falha(repo):
    ws = FakeWorkspace()
    coord = FakeCoordenador(excecao=RuntimeError("falhou"))
    uc, _, _, _ = caso(repo, workspace=ws, coordenador=coord)
    rodar(uc, repo)
    assert len(ws.descartados) == 1


def test_cancelar_enquanto_ainda_pendente_nao_tenta_processar(repo):
    uc, _, _, _ = caso(repo)
    revisao_id = uc.iniciar(URL, "back")
    revisao = repo.obter_revisao(revisao_id)
    revisao.status = StatusExecucao.CANCELADA  # usuário cancelou antes do background rodar
    repo.salvar_revisao(revisao)
    uc.executar(revisao_id)  # não deve levantar nem tentar reprocessar
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CANCELADA


def test_workspace_e_descartado_quando_cancelado_durante_os_agentes(repo):
    ws = FakeWorkspace()
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, workspace=ws, agente=ag)
    revisao_id = uc.iniciar(URL, "back")

    def executar_e_cancelar(agente, workspace, modelo, usuario, ao_progresso):
        r = repo.obter_revisao(revisao_id)
        r.status = StatusExecucao.CANCELADA
        repo.salvar_revisao(r)
        return ResultadoAgente(agente=agente.nome, achados=(achado(),))

    ag.executar = executar_e_cancelar
    uc.executar(revisao_id)
    assert repo.obter_revisao(revisao_id).status == StatusExecucao.CANCELADA
    assert repo.listar_apontamentos(revisao_id) == []
    assert len(ws.descartados) == 1


def test_escreve_patches_e_contexto_md_no_workspace(repo):
    mr = dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE))
    ws = FakeWorkspace()
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), workspace=ws)
    rodar(uc, repo)
    assert len(ws.contextos_escritos) == 1
    _, patches, contexto_md = ws.contextos_escritos[0]
    assert "src/ContratoService.java" in patches
    assert "Ajusta contrato" in contexto_md
    assert "src/ContratoService.java" in contexto_md


# ---------- R1: workspace do repositório ----------

def test_workspace_indisponivel_nao_consegue_revisar(repo):
    ws = FakeWorkspace(falhar_preparar=True)
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, workspace=ws, agente=ag)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.CONCLUIDA
    assert "clone falhou" in revisao.workspace_aviso
    assert "workspace do repositório não ficou pronto" in revisao.nota
    assert aps == []
    assert ag.chamadas == []  # sem workspace, agente nem chega a rodar


def test_sha_divergente_vira_erro_sem_rodar_agentes(repo):
    ws = FakeWorkspace(sha_divergente=True)
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, workspace=ws, agente=ag)
    revisao, aps = rodar(uc, repo)
    assert revisao.status == StatusExecucao.ERRO
    assert "sha divergente" in revisao.erro
    assert ag.chamadas == []
    assert aps == []


# ---------- R2: filtro de ruído e classificação de risco (inalterado, continua valendo) ----------

def test_mr_so_com_arquivo_vendorizado_nao_roda_agente_e_mostra_nada_a_revisar(repo):
    mr = dados_mr(arquivo("vendor/Gerado.java", DIFF_SERVICE))
    ag = FakePortaAgente()
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr), agente=ag)
    revisao, aps = rodar(uc, repo)
    assert ag.chamadas == []
    assert revisao.nota == "Nada a revisar após o filtro."
    assert revisao.arquivos_ignorados == "vendor/Gerado.java"
    assert aps == []


def test_nivel_de_risco_e_calculado_quando_nao_forcado(repo):
    uc, _, _, _ = caso(repo)
    revisao, _ = rodar(uc, repo)
    assert revisao.nivel_risco == "TRIVIAL"  # DIFF_SERVICE é pequeno, um arquivo só


def test_nivel_de_risco_forcado_prevalece_sobre_o_calculado(repo):
    from revisor.dominio.risco import NivelRisco
    uc, _, _, _ = caso(repo)
    revisao_id = uc.iniciar(URL, "back", nivel_forcado=NivelRisco.COMPLETO)
    uc.executar(revisao_id)
    assert repo.obter_revisao(revisao_id).nivel_risco == "COMPLETO"


def test_avaliar_risco_nao_grava_nada_no_banco(repo):
    uc, _, _, _ = caso(repo)
    avaliacao = uc.avaliar_risco(URL, "back")
    assert avaliacao.titulo == "Ajusta contrato"
    assert avaliacao.arquivos_mantidos == ["src/ContratoService.java"]
    assert avaliacao.arquivos_ignorados == []
    assert avaliacao.nivel.value == "TRIVIAL"
    assert repo.listar_revisoes() == []


def test_avaliar_risco_aplica_filtro_de_ruido(repo):
    mr = dados_mr(arquivo("vendor/Gerado.java", DIFF_SERVICE), arquivo("src/A.java", DIFF_SERVICE))
    uc, _, _, _ = caso(repo, gitlab=FakeGitLab(mr=mr))
    avaliacao = uc.avaliar_risco(URL, "back")
    assert avaliacao.arquivos_mantidos == ["src/A.java"]
    assert avaliacao.arquivos_ignorados == ["vendor/Gerado.java"]


def test_avaliar_risco_valida_entrada_como_iniciar(repo):
    uc, _, _, _ = caso(repo)
    with pytest.raises(ValueError):
        uc.avaliar_risco(URL, "inexistente")
