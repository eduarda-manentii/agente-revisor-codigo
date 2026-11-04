"""Interface web local. Só orquestra: regra de negócio fica nos casos de uso."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Status, TransicaoInvalida
from revisor.dominio.modelos import GERAL, Perfil, StatusExecucao
from revisor.dominio.progresso import esta_travado, formatar_duracao, transicionar
from revisor.dominio.prontidao import calcular_prontidao, comparar_com_anterior
from revisor.dominio.recomendacao import Recomendacao, calcular_recomendacao
from revisor.dominio.risco import NivelRisco
from revisor.portas import Repositorio

_PASTA = Path(__file__).parent

ROTULOS_MOTIVO = {
    MotivoRejeicao.FALSO_POSITIVO: "Não é um problema",
    MotivoRejeicao.IRRELEVANTE: "Irrelevante",
    MotivoRejeicao.JA_COBERTO: "Já apontado",
    MotivoRejeicao.TOM: "Tom inadequado",
    MotivoRejeicao.OUTRO: "Outro motivo",
}
ROTULOS_STATUS = {
    Status.PENDENTE: "A decidir",
    Status.APROVADO: "Aprovado",
    Status.REJEITADO: "Rejeitado",
    Status.PUBLICADO: "Publicado",
    Status.FALHA_PUBLICACAO: "Falhou ao publicar",
    Status.DESATUALIZADO: "MR mudou depois do review",
}
ROTULOS_NIVEL = {
    NivelRisco.TRIVIAL: "Trivial (mudança pequena e simples)",
    NivelRisco.LEVE: "Leve (mudança de porte médio)",
    NivelRisco.COMPLETO: "Completo (mudança grande ou sensível)",
}
ROTULOS_RECOMENDACAO = {
    Recomendacao.APROVAR: "Aprovar",
    Recomendacao.APROVAR_COM_COMENTARIOS: "Aprovar com comentários",
    Recomendacao.AJUSTES_NECESSARIOS: "Ajustes necessários",
    Recomendacao.MUDANCAS_SIGNIFICATIVAS: "Mudanças significativas",
}


@dataclass(frozen=True)
class Servicos:
    repo: Repositorio
    perfis: dict[str, Perfil]
    gitlab_url: str
    limite_inatividade_segundos: int
    revisar: RevisarMR
    triar: TriarApontamento
    publicar: PublicarAprovados
    treinar: TreinarPerfil


def _duracao(inicio: str, fim: str) -> str:
    if not inicio or not fim:
        return "00:00"
    try:
        return formatar_duracao(int((datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds()))
    except ValueError:
        return "00:00"


def _voltar(url: str, mensagem: str = "", erro: bool = False) -> RedirectResponse:
    if mensagem:
        separador = "&" if "?" in url else "?"
        url = f"{url}{separador}{'erro' if erro else 'msg'}={quote(mensagem)}"
    return RedirectResponse(url, status_code=303)


def criar_app(s: Servicos) -> FastAPI:
    app = FastAPI(title="Revisor", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_PASTA / "static"), name="static")
    templates = Jinja2Templates(directory=_PASTA / "templates")
    templates.env.globals.update(
        rotulos_motivo=ROTULOS_MOTIVO, rotulos_status=ROTULOS_STATUS, rotulos_nivel=ROTULOS_NIVEL,
        rotulos_recomendacao=ROTULOS_RECOMENDACAO,
        Status=Status, GERAL=GERAL, gitlab_url=s.gitlab_url, niveis_risco=list(NivelRisco),
    )

    def render(request: Request, nome: str, **contexto) -> HTMLResponse:
        contexto.update(msg=request.query_params.get("msg"), erro=request.query_params.get("erro"))
        return templates.TemplateResponse(request, nome, contexto)

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        perfis = [
            {
                "perfil": p,
                "treino": s.repo.ultimo_treino(p.nome),
                "guia": s.repo.guia_ativo(p.nome, GERAL),
                "exemplos": s.repo.contar_exemplos(p.nome),
                "pendentes": s.repo.contar_exemplos_pendentes(p.nome),
                "projetos": len(s.repo.contar_exemplos_por_projeto(p.nome)),
                "micros_com_guia": len(s.repo.listar_escopos_guia(p.nome)),
            }
            for p in s.perfis.values()
        ]
        atualizando = any(i["treino"] and i["treino"].status == "PROCESSANDO" for i in perfis)
        return render(request, "inicio.html", perfis=perfis, revisoes=s.repo.listar_revisoes(),
                      atualizando=atualizando, mapas=s.repo.listar_mapas())

    @app.post("/revisoes/pre", response_class=HTMLResponse)
    def pre_revisao(request: Request, url: str = Form(...), perfil: str = Form(...)):
        try:
            avaliacao = s.revisar.avaliar_risco(url, perfil)
        except ValueError as e:
            return _voltar("/", str(e), erro=True)
        return render(request, "revisao_confirmar.html", url=url, perfil=perfil, avaliacao=avaliacao)

    @app.post("/revisoes")
    def nova_revisao(
        tarefas: BackgroundTasks, url: str = Form(...), perfil: str = Form(...),
        nivel_risco: str = Form(""),
    ):
        try:
            nivel_forcado = NivelRisco(nivel_risco) if nivel_risco else None
            revisao_id = s.revisar.iniciar(url, perfil, nivel_forcado)
        except ValueError as e:
            return _voltar("/", str(e), erro=True)
        tarefas.add_task(s.revisar.executar, revisao_id)
        return _voltar(f"/revisoes/{revisao_id}")

    @app.get("/revisoes/{revisao_id}", response_class=HTMLResponse)
    def ver_revisao(request: Request, revisao_id: int):
        revisao = s.repo.obter_revisao(revisao_id)
        apontamentos = s.repo.listar_apontamentos(revisao_id)
        por_arquivo = [(arq, list(itens)) for arq, itens in groupby(apontamentos, key=lambda a: a.arquivo)]
        contagem = Counter(a.status for a in apontamentos)
        publicaveis = sum(1 for a in apontamentos if a.pode_publicar)
        fontes_exemplos = {
            ap.id: s.repo.obter_exemplos(revisao.perfil, list(ap.fontes.comentarios))
            for ap in apontamentos if ap.fontes and ap.fontes.comentarios
        }
        agora = datetime.now(timezone.utc)
        travado = esta_travado(revisao.atualizado_em, agora, s.limite_inatividade_segundos)
        fim = revisao.atualizado_em if revisao.status not in (
            StatusExecucao.PENDENTE, StatusExecucao.PROCESSANDO
        ) else agora.isoformat(timespec="seconds")

        prontidao = comparacao = revisao_anterior = recomendacao = None
        if revisao.status == StatusExecucao.CONCLUIDA:
            prontidao = calcular_prontidao(apontamentos)
            recomendacao = calcular_recomendacao(
                [a.severidade for a in apontamentos if a.status != Status.REJEITADO]
            )
            revisao_anterior = s.repo.obter_revisao_anterior(revisao.projeto, revisao.mr_iid, revisao.id)
            if revisao_anterior:
                comparacao = comparar_com_anterior(
                    apontamentos, s.repo.listar_apontamentos(revisao_anterior.id)
                )

        return render(request, "revisao.html", revisao=revisao, por_arquivo=por_arquivo,
                      contagem=contagem, total=len(apontamentos), publicaveis=publicaveis,
                      fontes_exemplos=fontes_exemplos, eventos=s.repo.listar_eventos(revisao_id),
                      travado=travado, limite_inatividade=s.limite_inatividade_segundos,
                      duracao_total=_duracao(revisao.criada_em, fim),
                      duracao_etapa=_duracao(revisao.etapa_iniciada_em, fim),
                      prontidao=prontidao, comparacao=comparacao, revisao_anterior=revisao_anterior,
                      recomendacao=recomendacao, descartados_coordenador=s.repo.listar_descartes(revisao_id),
                      execucoes_agentes=s.repo.listar_execucoes_agentes(revisao_id))

    @app.get("/revisoes/{revisao_id}/eventos")
    async def eventos_revisao(revisao_id: int):
        async def emitir():
            while True:
                revisao = s.repo.obter_revisao(revisao_id)
                payload = {
                    "status": revisao.status.value,
                    "etapa": revisao.etapa,
                    "etapa_iniciada_em": revisao.etapa_iniciada_em,
                    "atualizado_em": revisao.atualizado_em,
                    "criada_em": revisao.criada_em,
                    "travado": esta_travado(
                        revisao.atualizado_em, datetime.now(timezone.utc), s.limite_inatividade_segundos
                    ),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if revisao.status in (StatusExecucao.CONCLUIDA, StatusExecucao.ERRO, StatusExecucao.CANCELADA):
                    return
                await asyncio.sleep(1)

        return StreamingResponse(emitir(), media_type="text/event-stream")

    @app.post("/revisoes/{revisao_id}/cancelar")
    def cancelar_revisao(revisao_id: int):
        destino = f"/revisoes/{revisao_id}"
        revisao = s.repo.obter_revisao(revisao_id)
        try:
            revisao.status = transicionar(revisao.status, StatusExecucao.CANCELADA)
        except TransicaoInvalida as e:
            return _voltar(destino, str(e), erro=True)
        s.repo.salvar_revisao(revisao)
        return _voltar(destino, "Revisão cancelada.")

    @app.post("/revisoes/{revisao_id}/reiniciar")
    def reiniciar_revisao(tarefas: BackgroundTasks, revisao_id: int):
        atual = s.repo.obter_revisao(revisao_id)
        if atual.status in (StatusExecucao.PENDENTE, StatusExecucao.PROCESSANDO):
            atual.status = transicionar(atual.status, StatusExecucao.CANCELADA)
            s.repo.salvar_revisao(atual)
        nivel_forcado = NivelRisco(atual.nivel_risco) if atual.nivel_risco else None
        novo_id = s.revisar.iniciar(atual.mr_url, atual.perfil, nivel_forcado)
        tarefas.add_task(s.revisar.executar, novo_id)
        return _voltar(f"/revisoes/{novo_id}")

    def _triagem(revisao_id: int, apontamento_id: int, acao) -> RedirectResponse:
        destino = f"/revisoes/{revisao_id}"
        try:
            acao()
        except TransicaoInvalida as e:
            return _voltar(destino, str(e), erro=True)
        return RedirectResponse(f"{destino}#ap-{apontamento_id}", status_code=303)

    @app.post("/revisoes/{revisao_id}/descartes/{descarte_id}/recuperar")
    def recuperar_descarte(revisao_id: int, descarte_id: int):
        destino = f"/revisoes/{revisao_id}"
        descarte = s.repo.obter_descarte(descarte_id)
        ap = Apontamento(
            revisao_id=revisao_id, arquivo=descarte.arquivo, caminho_antigo=descarte.arquivo,
            linha=descarte.linha, linha_antiga=None, severidade=descarte.severidade,
            confianca=descarte.confianca, texto_original=descarte.comentario,
            trecho=descarte.evidencia, origens=", ".join(descarte.origens),
        )
        s.repo.adicionar_apontamentos([ap])
        s.repo.marcar_descarte_recuperado(descarte_id)
        return RedirectResponse(f"{destino}#ap-{ap.id}", status_code=303)

    @app.post("/revisoes/{revisao_id}/apontamentos/{ap_id}/aprovar")
    def aprovar(revisao_id: int, ap_id: int, texto: str = Form(...)):
        return _triagem(revisao_id, ap_id, lambda: s.triar.aprovar(ap_id, texto))

    @app.post("/revisoes/{revisao_id}/apontamentos/{ap_id}/rejeitar")
    def rejeitar(revisao_id: int, ap_id: int, motivo: MotivoRejeicao = Form(...)):
        return _triagem(revisao_id, ap_id, lambda: s.triar.rejeitar(ap_id, motivo))

    @app.post("/revisoes/{revisao_id}/apontamentos/{ap_id}/reabrir")
    def reabrir(revisao_id: int, ap_id: int):
        return _triagem(revisao_id, ap_id, lambda: s.triar.reabrir(ap_id))

    @app.post("/revisoes/{revisao_id}/publicar")
    def publicar(revisao_id: int):
        destino = f"/revisoes/{revisao_id}"
        try:
            r = s.publicar.executar(revisao_id)
        except Exception as e:  # erro de rede/autenticação antes de publicar qualquer item
            return _voltar(destino, f"Não foi possível falar com o GitLab: {e}", erro=True)
        if r.desatualizados:
            return _voltar(destino, f"O MR recebeu commits depois do review. Rode um novo review: "
                                    f"{r.desatualizados} comentário(s) não foram publicados.", erro=True)
        if r.falhas:
            return _voltar(destino, f"{r.publicados} publicado(s), {r.falhas} com falha. "
                                    "Veja o erro em cada um e tente de novo.", erro=True)
        return _voltar(destino, f"{r.publicados} comentário(s) publicado(s) no MR.")

    @app.post("/perfis/{nome}/treinar")
    def treinar(tarefas: BackgroundTasks, nome: str, completo: bool = Form(False)):
        try:
            treino_id = s.treinar.iniciar(nome, completo=completo)
        except ValueError as e:
            return _voltar("/", str(e), erro=True)
        tarefas.add_task(s.treinar.executar, treino_id)
        return _voltar("/", f"Treino do perfil {nome} iniciado.")

    @app.get("/perfis/{nome}/guia", response_class=HTMLResponse)
    def ver_guia(request: Request, nome: str, escopo: str = GERAL, versao: int | None = None):
        guia = s.repo.guia_por_versao(nome, versao, escopo) if versao else s.repo.guia_ativo(nome, escopo)
        contagem_projetos = s.repo.contar_exemplos_por_projeto(nome) if escopo == GERAL else []
        return render(request, "guia.html", perfil=s.perfis[nome], guia=guia, escopo=escopo,
                      escopos=s.repo.listar_escopos_guia(nome),
                      versoes=s.repo.listar_versoes_guia(nome, escopo),
                      contagem_projetos=contagem_projetos)

    @app.get("/mapas", response_class=HTMLResponse)
    def ver_mapas(request: Request, projeto: str | None = None):
        mapas = s.repo.listar_mapas()
        mapa = s.repo.mapa_ativo(projeto) if projeto else (
            s.repo.mapa_ativo(mapas[0].projeto) if mapas else None
        )
        return render(request, "mapas.html", mapas=mapas, mapa=mapa)

    return app
