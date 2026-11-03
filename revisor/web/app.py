"""Interface web local. Só orquestra: regra de negócio fica nos casos de uso."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from revisor.aplicacao.revisar import RevisarMR
from revisor.aplicacao.treinar import TreinarPerfil
from revisor.aplicacao.triagem_publicacao import PublicarAprovados, TriarApontamento
from revisor.dominio.apontamento import MotivoRejeicao, Status, TransicaoInvalida
from revisor.dominio.modelos import Perfil
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


@dataclass(frozen=True)
class Servicos:
    repo: Repositorio
    perfis: dict[str, Perfil]
    revisar: RevisarMR
    triar: TriarApontamento
    publicar: PublicarAprovados
    treinar: TreinarPerfil


def _voltar(url: str, mensagem: str = "", erro: bool = False) -> RedirectResponse:
    if mensagem:
        separador = "&" if "?" in url else "?"
        url = f"{url}{separador}{'erro' if erro else 'msg'}={quote(mensagem)}"
    return RedirectResponse(url, status_code=303)


def criar_app(s: Servicos) -> FastAPI:
    app = FastAPI(title="Revisor", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_PASTA / "static"), name="static")
    templates = Jinja2Templates(directory=_PASTA / "templates")
    templates.env.globals.update(rotulos_motivo=ROTULOS_MOTIVO, rotulos_status=ROTULOS_STATUS, Status=Status)

    def render(request: Request, nome: str, **contexto) -> HTMLResponse:
        contexto.update(msg=request.query_params.get("msg"), erro=request.query_params.get("erro"))
        return templates.TemplateResponse(request, nome, contexto)

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        perfis = [
            {
                "perfil": p,
                "treino": s.repo.ultimo_treino(p.nome),
                "guia": s.repo.guia_ativo(p.nome),
                "exemplos": s.repo.contar_exemplos(p.nome),
                "pendentes": s.repo.contar_exemplos_pendentes(p.nome),
            }
            for p in s.perfis.values()
        ]
        atualizando = any(i["treino"] and i["treino"].status == "PROCESSANDO" for i in perfis)
        return render(request, "inicio.html", perfis=perfis,
                      revisoes=s.repo.listar_revisoes(), atualizando=atualizando)

    @app.post("/revisoes")
    def nova_revisao(tarefas: BackgroundTasks, url: str = Form(...), perfil: str = Form(...)):
        try:
            revisao_id = s.revisar.iniciar(url, perfil)
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
        return render(request, "revisao.html", revisao=revisao, por_arquivo=por_arquivo,
                      contagem=contagem, total=len(apontamentos), publicaveis=publicaveis)

    def _triagem(revisao_id: int, apontamento_id: int, acao) -> RedirectResponse:
        destino = f"/revisoes/{revisao_id}"
        try:
            acao()
        except TransicaoInvalida as e:
            return _voltar(destino, str(e), erro=True)
        return RedirectResponse(f"{destino}#ap-{apontamento_id}", status_code=303)

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
    def ver_guia(request: Request, nome: str, versao: int | None = None):
        guia = s.repo.guia_por_versao(nome, versao) if versao else s.repo.guia_ativo(nome)
        return render(request, "guia.html", perfil=s.perfis[nome], guia=guia,
                      versoes=s.repo.listar_versoes_guia(nome))

    return app
