"""Caso de uso: gerar apontamentos para um MR com um perfil (back/front).

v3: a chamada única ao LLM foi substituída por agentes especialistas (R3, via `ExecutarAgentes`)
mais um coordenador que consolida os achados (R4). Os agentes precisam ler o código de verdade
(R1): sem workspace, não há como eles trabalharem — diferente da v2, não existe mais um modo
"só diff" de fallback para a avaliação em si (só para o cabeçalho do filtro de ruído, R2)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from revisor import prompts
from revisor.aplicacao.executar_agentes import ExecutarAgentes
from revisor.dominio.apontamento import Apontamento
from revisor.dominio.consolidacao import GrupoAchados, pre_consolidar
from revisor.dominio.coordenador import (
    ApontamentoFinal,
    Descarte,
    ResultadoCoordenacao,
    aplicar_limite,
    interpretar_saida_coordenador,
)
from revisor.dominio.diff import ArquivoDiff
from revisor.dominio.filtro_diff import filtrar_arquivos
from revisor.dominio.modelos import GERAL, DadosMR, Perfil, RefMR, Revisao, StatusExecucao, parse_url_mr
from revisor.dominio.progresso import RevisaoCancelada, formatar_contagem, transicionar
from revisor.dominio.risco import NivelRisco, arquivo_sensivel, classificar_risco
from revisor.portas import (
    PortaCoordenador,
    PortaGitLab,
    PortaWorkspace,
    Repositorio,
    Workspace,
    WorkspaceIndisponivel,
)

log = logging.getLogger(__name__)

_LINHAS_CABECALHO = 5
_MODELO_COORDENADOR = "sonnet"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _contar_linhas_alteradas(arquivos: list[ArquivoDiff]) -> int:
    return sum(1 for a in arquivos for l in a.linhas if l.tipo in ("+", "-"))


@dataclass(frozen=True)
class AvaliacaoRisco:
    """Pré-visualização do que vai ser revisado, sem gravar nada no banco (R2)."""
    titulo: str
    arquivos_mantidos: list[str]
    arquivos_ignorados: list[str]
    num_linhas: int
    nivel: NivelRisco


class RevisarMR:
    def __init__(
        self,
        gitlab: PortaGitLab,
        repo: Repositorio,
        perfis: dict[str, Perfil],
        host_gitlab: str,
        workspace: PortaWorkspace,
        executar_agentes: ExecutarAgentes,
        coordenador: PortaCoordenador,
    ) -> None:
        self._gitlab = gitlab
        self._repo = repo
        self._perfis = perfis
        self._host = host_gitlab.lower()
        self._workspace = workspace
        self._executar_agentes = executar_agentes
        self._coordenador = coordenador

    def _validar_entrada(self, url: str, nome_perfil: str) -> RefMR:
        if nome_perfil not in self._perfis:
            raise ValueError(f"Perfil desconhecido: {nome_perfil}")
        ref = parse_url_mr(url)
        if ref.host != self._host:
            raise ValueError(f"O MR é de {ref.host}, mas o GitLab configurado é {self._host}.")
        return ref

    def iniciar(self, url: str, nome_perfil: str, nivel_forcado: NivelRisco | None = None) -> int:
        """Valida a entrada e registra a revisão. O trabalho pesado fica em `executar`."""
        ref = self._validar_entrada(url, nome_perfil)
        return self._repo.criar_revisao(
            Revisao(
                mr_url=url.strip(), projeto=ref.projeto, mr_iid=ref.iid, perfil=nome_perfil,
                nivel_risco=nivel_forcado.value if nivel_forcado else "",
            )
        )

    def _arquivos_do_perfil(self, mr: DadosMR, perfil: Perfil) -> list[ArquivoDiff]:
        return [
            a for a in mr.arquivos
            if not a.removido and perfil.aceita(a.caminho_novo) and a.linhas_comentaveis()
        ]

    def avaliar_risco(self, url: str, nome_perfil: str) -> AvaliacaoRisco:
        """Busca o MR e aplica filtro de ruído + classificação de risco, sem gravar nada (R2)."""
        ref = self._validar_entrada(url, nome_perfil)
        perfil = self._perfis[nome_perfil]
        mr = self._gitlab.obter_mr(ref.projeto, ref.iid)
        arquivos = self._arquivos_do_perfil(mr, perfil)
        cabecalhos = {
            a.caminho_novo: "\n".join((self._gitlab.obter_arquivo(ref.projeto, a.caminho_novo, mr.head_sha) or "")
                                      .splitlines()[:_LINHAS_CABECALHO])
            for a in arquivos
        }
        mantidos, ignorados = filtrar_arquivos(arquivos, cabecalhos, perfil.ignorar_arquivos, perfil.nunca_ignorar)
        num_linhas = _contar_linhas_alteradas(mantidos)
        sensivel = any(arquivo_sensivel(a.caminho_novo) for a in mantidos)
        nivel = classificar_risco(num_linhas, len(mantidos), sensivel)
        return AvaliacaoRisco(
            titulo=mr.titulo, arquivos_mantidos=[a.caminho_novo for a in mantidos],
            arquivos_ignorados=ignorados, num_linhas=num_linhas, nivel=nivel,
        )

    def executar(self, revisao_id: int) -> None:
        revisao = self._repo.obter_revisao(revisao_id)
        if revisao.status != StatusExecucao.PENDENTE:
            return  # já cancelada (ex.: enquanto ainda PENDENTE, antes de começar) ou já terminou
        try:
            revisao.status = transicionar(revisao.status, StatusExecucao.PROCESSANDO)
            self._repo.salvar_revisao(revisao)
            self._processar(revisao)
            revisao.status = transicionar(revisao.status, StatusExecucao.CONCLUIDA)
        except RevisaoCancelada:
            revisao.status = transicionar(revisao.status, StatusExecucao.CANCELADA)
        except Exception as erro:  # registra qualquer falha para aparecer na tela
            log.exception("Falha na revisão %s", revisao_id)
            revisao.status = transicionar(revisao.status, StatusExecucao.ERRO)
            revisao.erro = str(erro) or erro.__class__.__name__
        revisao.atualizado_em = _agora()
        self._repo.salvar_revisao(revisao)

    def _progresso(self, revisao: Revisao, etapa: str, atual: int | None = None, total: int | None = None) -> None:
        contagem = formatar_contagem(atual, total)
        texto = f"{etapa} ({contagem})..." if contagem else f"{etapa}..."
        agora = _agora()
        if texto != revisao.etapa:
            revisao.etapa_iniciada_em = agora
        revisao.etapa = texto
        revisao.atualizado_em = agora
        self._repo.salvar_revisao(revisao)
        self._repo.registrar_evento(revisao.id, texto, agora)

    def _verificar_cancelamento(self, revisao: Revisao) -> None:
        if self._repo.obter_revisao(revisao.id).status == StatusExecucao.CANCELADA:
            raise RevisaoCancelada()

    def _processar(self, revisao: Revisao) -> None:
        perfil = self._perfis[revisao.perfil]
        self._progresso(revisao, "Carregando diff do MR")
        mr = self._gitlab.obter_mr(revisao.projeto, revisao.mr_iid)
        revisao.titulo_mr = mr.titulo
        revisao.base_sha, revisao.start_sha, revisao.head_sha = mr.base_sha, mr.start_sha, mr.head_sha

        arquivos = self._arquivos_do_perfil(mr, perfil)
        if not arquivos:
            revisao.nota = f"Nenhum arquivo do perfil {perfil.nome} neste MR."
            return

        self._verificar_cancelamento(revisao)
        workspace: Workspace | None = None
        try:
            try:
                workspace = self._workspace.preparar(revisao.projeto, revisao.mr_iid, mr.head_sha)
            except WorkspaceIndisponivel as erro:
                revisao.workspace_aviso = str(erro) or erro.__class__.__name__

            brutos = self._buscar_brutos(revisao.projeto, arquivos, mr.head_sha, workspace)
            cabecalhos = {c: "\n".join(v.splitlines()[:_LINHAS_CABECALHO]) for c, v in brutos.items()}
            arquivos, ignorados = filtrar_arquivos(
                arquivos, cabecalhos, perfil.ignorar_arquivos, perfil.nunca_ignorar
            )
            revisao.arquivos_ignorados = "\n".join(ignorados)
            if not arquivos:
                revisao.nota = "Nada a revisar após o filtro."
                return
            if not revisao.nivel_risco:
                sensivel = any(arquivo_sensivel(a.caminho_novo) for a in arquivos)
                revisao.nivel_risco = classificar_risco(
                    _contar_linhas_alteradas(arquivos), len(arquivos), sensivel
                ).value

            if workspace is None:
                # Os agentes especialistas (R3) leem o código do workspace: sem ele, não têm como
                # trabalhar. Diferente da v2, não existe mais chamada única pra cair como fallback.
                revisao.nota = (
                    f"Não foi possível revisar: o workspace do repositório não ficou pronto "
                    f"({revisao.workspace_aviso})."
                )
                return

            contexto_md = prompts.contexto_mr_md(
                mr.titulo, mr.descricao, [a.caminho_novo for a in arquivos], revisao.nivel_risco
            )
            patches = {a.caminho_novo: a.anotado() for a in arquivos}
            self._workspace.escrever_contexto(workspace, patches, contexto_md)

            self._progresso(revisao, "Consultando o guia de padrões")
            guia_geral = self._repo.guia_ativo(perfil.nome, GERAL)
            guia_micro = self._repo.guia_ativo(perfil.nome, revisao.projeto)
            mapa = self._repo.mapa_ativo(revisao.projeto)
            revisao.guia_versao = guia_geral.versao if guia_geral else None
            revisao.guia_micro_versao = guia_micro.versao if guia_micro else None
            revisao.mapa_em = mapa.criado_em if mapa else ""
            exemplos = self._repo.listar_exemplos(perfil.nome)
            codigo_alvo = "\n".join(a.texto_adicionado() for a in arquivos)

            self._verificar_cancelamento(revisao)
            nomes_agentes = perfil.agentes_do_nivel(revisao.nivel_risco)
            self._progresso(revisao, "Agentes especialistas trabalhando", 0, len(nomes_agentes))
            resultados = self._executar_agentes.rodar(
                revisao.id, perfil, revisao.nivel_risco, workspace,
                [a.caminho_novo for a in arquivos], exemplos, guia_micro or guia_geral, codigo_alvo,
            )
            for resultado in resultados:
                if resultado.erro:
                    self._repo.registrar_evento(
                        revisao.id, f"Agente {resultado.agente} falhou: {resultado.erro}", _agora()
                    )

            achados = [a for r in resultados for a in r.achados]
            grupos = pre_consolidar(achados)
            if not grupos:
                falhas = sum(1 for r in resultados if r.erro)
                revisao.nota = "Nenhum achado dos agentes especialistas."
                if falhas:
                    revisao.nota += f" ({falhas} agente(s) falharam.)"
                return

            self._verificar_cancelamento(revisao)
            self._progresso(revisao, "Coordenador consolidando")
            resultado_coord = self._rodar_coordenador(revisao, perfil, workspace, grupos, guia_geral, guia_micro)
            resultado_coord = aplicar_limite(resultado_coord, perfil.max_apontamentos)

            por_caminho = {a.caminho_novo: a for a in arquivos}
            apontamentos: list[Apontamento] = []
            descartes_finais = list(resultado_coord.descartados)
            for final in resultado_coord.apontamentos:
                arquivo = por_caminho.get(final.arquivo)
                linha = arquivo.linha(final.linha) if arquivo else None
                if arquivo is None or linha is None:
                    descartes_finais.append(Descarte(
                        arquivo=final.arquivo, linha=final.linha, severidade=final.severidade,
                        confianca=final.confianca, comentario=final.comentario, evidencia="",
                        motivo="Linha fora do diff.", origens=final.origens,
                    ))
                    continue
                apontamentos.append(Apontamento(
                    revisao_id=revisao.id, arquivo=arquivo.caminho_novo,
                    caminho_antigo=arquivo.caminho_antigo, linha=final.linha,
                    linha_antiga=linha.linha_antiga if linha.tipo == " " else None,
                    severidade=final.severidade, confianca=final.confianca,
                    texto_original=final.comentario, trecho=arquivo.trecho(final.linha),
                    origens=", ".join(final.origens),
                ))

            self._repo.adicionar_apontamentos(apontamentos)
            self._repo.salvar_descartes(revisao.id, descartes_finais)
            if not apontamentos and not revisao.nota:
                revisao.nota = "O coordenador não aprovou nenhum apontamento."
        finally:
            if workspace is not None:
                self._workspace.descartar(workspace)

    def _rodar_coordenador(
        self, revisao: Revisao, perfil: Perfil, workspace: Workspace, grupos: list[GrupoAchados],
        guia_geral, guia_micro,
    ) -> ResultadoCoordenacao:
        sistema = prompts.sistema_coordenador(perfil.nome)
        usuario = prompts.usuario_coordenador(grupos, guia_geral, guia_micro)

        def ao_progresso(evento) -> None:
            self._progresso(revisao, f"Coordenador: {evento.descricao}")

        for tentativa in range(2):
            try:
                texto = self._coordenador.executar(workspace, _MODELO_COORDENADOR, sistema, usuario, ao_progresso)
            except Exception as erro:
                revisao.nota = f"Consolidação indisponível: {erro}"
                return self._fallback_coordenacao(grupos)
            try:
                return interpretar_saida_coordenador(texto, grupos)
            except ValueError as e:
                if tentativa == 0:
                    usuario = f"{usuario}\n\n# Sua resposta anterior falhou: {e}\nResponda só com o objeto JSON."
                    continue
                revisao.nota = f"Consolidação indisponível: {e}"
                return self._fallback_coordenacao(grupos)
        return self._fallback_coordenacao(grupos)  # inalcançável, só pra satisfazer o checador de tipos

    @staticmethod
    def _fallback_coordenacao(grupos: list[GrupoAchados]) -> ResultadoCoordenacao:
        """Coordenador falhou (R4.8): cada grupo vira apontamento direto (achado de maior
        confiança), sem perder o trabalho dos agentes."""
        apontamentos = []
        for g in grupos:
            principal = max(g.achados, key=lambda a: a.confianca)
            apontamentos.append(ApontamentoFinal(
                arquivo=g.arquivo, linha=g.linha, severidade=principal.severidade,
                confianca=principal.confianca, comentario=principal.comentario, origens=g.origens,
            ))
        return ResultadoCoordenacao(apontamentos=tuple(apontamentos))

    def _buscar_brutos(
        self, projeto: str, arquivos: list[ArquivoDiff], ref: str, workspace: Workspace | None
    ) -> dict[str, str]:
        """Conteúdo completo do arquivo no head_sha do MR, por caminho: lê do workspace local
        quando disponível (R1), senão cai na API do GitLab — usado só pro cabeçalho do filtro de
        ruído (R2), já que os agentes leem o código sozinhos a partir do workspace."""
        brutos: dict[str, str] = {}
        for arquivo in arquivos:
            conteudo = self._workspace.ler_arquivo(workspace, arquivo.caminho_novo) if workspace else None
            if conteudo is None:
                conteudo = self._gitlab.obter_arquivo(projeto, arquivo.caminho_novo, ref)
            if conteudo is not None:
                brutos[arquivo.caminho_novo] = conteudo
        return brutos
