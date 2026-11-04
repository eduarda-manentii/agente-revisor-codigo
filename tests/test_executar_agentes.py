from revisor.aplicacao.executar_agentes import ExecutarAgentes
from revisor.dominio.agentes import ResultadoAgente
from revisor.dominio.modelos import Agente, Perfil, Revisao
from revisor.portas import Workspace
from tests.fakes import FakePortaAgente

AGENTES = {
    "qualidade": Agente(nome="qualidade", instrucoes="instr qualidade"),
    "estilo-revisor": Agente(nome="estilo-revisor", instrucoes="instr estilo"),
    "testes": Agente(nome="testes", instrucoes="instr testes"),
    "seguranca": Agente(nome="seguranca", instrucoes="instr seguranca", modelo_padrao="opus"),
}

PERFIL = Perfil(
    nome="back", descricao="Java", extensoes=(".java",), instrucoes="instrucoes",
    agentes_por_risco={
        "TRIVIAL": (),
        "LEVE": ("qualidade", "estilo-revisor", "testes"),
        "COMPLETO": ("qualidade", "estilo-revisor", "testes", "seguranca"),
    },
)

WS = Workspace(caminho="/fake/ws", repo_cache="/fake/cache")


def nova_revisao(repo) -> int:
    return repo.criar_revisao(Revisao("u", "g/p", 1, "back"))


def test_nivel_sem_agentes_nao_chama_nada(repo):
    porta = FakePortaAgente()
    uc = ExecutarAgentes(porta, repo, AGENTES)
    revisao_id = nova_revisao(repo)
    resultado = uc.rodar(revisao_id, PERFIL, "TRIVIAL", WS, ["A.java"])
    assert resultado == []
    assert porta.chamadas == []


def test_falha_de_um_agente_nao_derruba_os_outros(repo):
    porta = FakePortaAgente(respostas={"testes": ResultadoAgente(agente="testes", erro="deu ruim")})
    uc = ExecutarAgentes(porta, repo, AGENTES)
    revisao_id = nova_revisao(repo)
    resultados = uc.rodar(revisao_id, PERFIL, "LEVE", WS, ["A.java"])
    assert len(resultados) == 3
    por_nome = {r.agente: r for r in resultados}
    assert por_nome["testes"].erro == "deu ruim"
    assert por_nome["qualidade"].erro == ""
    assert por_nome["estilo-revisor"].erro == ""


def test_respeita_o_limite_de_agentes_paralelos(repo):
    porta = FakePortaAgente(atraso=0.05)
    uc = ExecutarAgentes(porta, repo, AGENTES, agentes_paralelos=2)
    revisao_id = nova_revisao(repo)
    uc.rodar(revisao_id, PERFIL, "COMPLETO", WS, ["A.java"])
    assert porta.pico_concorrencia <= 2
    assert porta.pico_concorrencia >= 2  # com atraso e 4 agentes, dá tempo de empilhar 2 ao mesmo tempo


def test_disjuntor_troca_modelo_depois_de_duas_sobrecargas(repo):
    porta = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(agente="qualidade", erro="overloaded_error"),
        "estilo-revisor": ResultadoAgente(agente="estilo-revisor", erro="overloaded_error"),
    })
    uc = ExecutarAgentes(porta, repo, AGENTES, agentes_paralelos=1)  # sequencial, ordem previsível
    revisao_id = nova_revisao(repo)
    uc.rodar(revisao_id, PERFIL, "LEVE", WS, ["A.java"])
    execucoes = {e.agente: e for e in repo.listar_execucoes_agentes(revisao_id)}
    # qualidade e estilo-revisor sobrecarregaram com o modelo padrão (sonnet); testes, rodando por
    # último, já deveria ter trocado pro modelo de reserva (haiku).
    assert execucoes["testes"].modelo == "haiku"


def test_achados_descartados_e_resposta_bruta_vao_pra_execucao_agente(repo):
    from revisor.dominio.agentes import Achado
    from revisor.dominio.apontamento import Severidade
    porta = FakePortaAgente(respostas={
        "qualidade": ResultadoAgente(
            agente="qualidade",
            achados=(Achado("A.java", 1, Severidade.P1, 8, "qualidade", "x", "y"),),
            descartados=2, resposta_bruta='[{"a": 1}]',
        ),
        "testes": ResultadoAgente(agente="testes", erro="Saída inválida: lixo", resposta_bruta="lixo"),
    })
    uc = ExecutarAgentes(porta, repo, AGENTES)
    revisao_id = nova_revisao(repo)
    uc.rodar(revisao_id, PERFIL, "LEVE", WS, ["A.java"])
    execucoes = {e.agente: e for e in repo.listar_execucoes_agentes(revisao_id)}

    assert execucoes["qualidade"].achados_validos == 1
    assert execucoes["qualidade"].achados_descartados == 2
    assert execucoes["qualidade"].resposta_bruta == '[{"a": 1}]'

    assert execucoes["testes"].achados_validos == 0
    assert execucoes["testes"].resposta_bruta == "lixo"


def test_progresso_grava_em_agentes_execucao_e_eventos_revisao(repo):
    porta = FakePortaAgente()
    uc = ExecutarAgentes(porta, repo, AGENTES, agentes_paralelos=1)
    revisao_id = nova_revisao(repo)
    uc.rodar(revisao_id, PERFIL, "LEVE", WS, ["A.java"])

    execucoes = repo.listar_execucoes_agentes(revisao_id)
    assert {e.agente for e in execucoes} == {"qualidade", "estilo-revisor", "testes"}
    assert all(e.estado == "CONCLUIDO" for e in execucoes)
    assert all(e.modelo for e in execucoes)

    eventos = [e.etapa for e in repo.listar_eventos(revisao_id)]
    assert any("Lendo qualidade.java" in e for e in eventos)
