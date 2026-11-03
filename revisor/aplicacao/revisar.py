"""Caso de uso: gerar apontamentos para um MR com um perfil (back/front)."""
from __future__ import annotations

import logging

from revisor import prompts
from revisor.dominio.apontamento import Apontamento, Severidade
from revisor.dominio.diff import ArquivoDiff
from revisor.dominio.fontes import verificar_fontes
from revisor.dominio.heuristicas import ApontamentoSugerido, parse_saida_llm, selecionar_exemplos
from revisor.dominio.modelos import GERAL, Perfil, Revisao, StatusExecucao, parse_url_mr
from revisor.portas import PortaGitLab, PortaLLM, Repositorio

log = logging.getLogger(__name__)

_ORDEM_SEVERIDADE = {Severidade.P0: 0, Severidade.P1: 1, Severidade.P2: 2}
_LIMITE_ARQUIVO_COMPLETO = 40_000


class RevisarMR:
    def __init__(
        self,
        gitlab: PortaGitLab,
        llm: PortaLLM,
        repo: Repositorio,
        perfis: dict[str, Perfil],
        host_gitlab: str,
        max_caracteres_lote: int = 60_000,
        exemplos_por_lote: int = 12,
    ) -> None:
        self._gitlab = gitlab
        self._llm = llm
        self._repo = repo
        self._perfis = perfis
        self._host = host_gitlab.lower()
        self._max_lote = max_caracteres_lote
        self._k = exemplos_por_lote

    def iniciar(self, url: str, nome_perfil: str) -> int:
        """Valida a entrada e registra a revisão. O trabalho pesado fica em `executar`."""
        if nome_perfil not in self._perfis:
            raise ValueError(f"Perfil desconhecido: {nome_perfil}")
        ref = parse_url_mr(url)
        if ref.host != self._host:
            raise ValueError(f"O MR é de {ref.host}, mas o GitLab configurado é {self._host}.")
        return self._repo.criar_revisao(
            Revisao(mr_url=url.strip(), projeto=ref.projeto, mr_iid=ref.iid, perfil=nome_perfil)
        )

    def executar(self, revisao_id: int) -> None:
        revisao = self._repo.obter_revisao(revisao_id)
        try:
            self._processar(revisao)
            revisao.status = StatusExecucao.CONCLUIDA
        except Exception as erro:  # registra qualquer falha para aparecer na tela
            log.exception("Falha na revisão %s", revisao_id)
            revisao.status = StatusExecucao.ERRO
            revisao.erro = str(erro) or erro.__class__.__name__
        self._repo.salvar_revisao(revisao)

    def _processar(self, revisao: Revisao) -> None:
        perfil = self._perfis[revisao.perfil]
        mr = self._gitlab.obter_mr(revisao.projeto, revisao.mr_iid)
        revisao.titulo_mr = mr.titulo
        revisao.base_sha, revisao.start_sha, revisao.head_sha = mr.base_sha, mr.start_sha, mr.head_sha

        arquivos = [
            a for a in mr.arquivos
            if not a.removido and perfil.aceita(a.caminho_novo) and a.linhas_comentaveis()
        ]
        if not arquivos:
            revisao.nota = f"Nenhum arquivo do perfil {perfil.nome} neste MR."
            return

        guia_geral = self._repo.guia_ativo(perfil.nome, GERAL)
        guia_micro = self._repo.guia_ativo(perfil.nome, revisao.projeto)
        mapa = self._repo.mapa_ativo(revisao.projeto)
        revisao.guia_versao = guia_geral.versao if guia_geral else None
        revisao.guia_micro_versao = guia_micro.versao if guia_micro else None
        revisao.mapa_em = mapa.criado_em if mapa else ""
        exemplos = self._repo.listar_exemplos(perfil.nome)
        sistema = prompts.sistema_revisao(perfil, guia_geral, guia_micro, mapa)
        conteudos = self._conteudos_completos(revisao.projeto, arquivos, mr.head_sha)

        candidatos: list[Apontamento] = []
        for lote in self._agrupar(arquivos, conteudos):
            selecionados = selecionar_exemplos(
                "\n".join(a.texto_adicionado() for a in lote), exemplos, self._k,
                projeto_mr=revisao.projeto,
            )
            usuario = prompts.usuario_revisao(mr.titulo, mr.descricao, lote, selecionados, conteudos)
            sugeridos, invalidos = parse_saida_llm(self._llm.completar(sistema, usuario))
            revisao.descartados += invalidos
            validos, fora_do_diff = self._validar(
                sugeridos, lote, perfil, revisao.id, guia_geral, guia_micro
            )
            revisao.descartados += fora_do_diff
            candidatos += validos

        candidatos.sort(key=lambda a: (_ORDEM_SEVERIDADE[a.severidade], -a.confianca))
        escolhidos = candidatos[: perfil.max_apontamentos]
        self._repo.adicionar_apontamentos(escolhidos)
        if not escolhidos:
            revisao.nota = "O agente não encontrou nada relevante."

    def _conteudos_completos(
        self, projeto: str, arquivos: list[ArquivoDiff], ref: str
    ) -> dict[str, str]:
        """Arquivo completo no head_sha do MR, por caminho. Acima do limite, só o diff mesmo."""
        conteudos: dict[str, str] = {}
        for arquivo in arquivos:
            conteudo = self._gitlab.obter_arquivo(projeto, arquivo.caminho_novo, ref)
            if conteudo is not None and len(conteudo) <= _LIMITE_ARQUIVO_COMPLETO:
                conteudos[arquivo.caminho_novo] = conteudo
        return conteudos

    def _agrupar(
        self, arquivos: list[ArquivoDiff], conteudos: dict[str, str]
    ) -> list[list[ArquivoDiff]]:
        """Divide o diff em lotes por orçamento de caracteres (diff + arquivo completo, se houver).

        Arquivo grande vai sozinho."""
        lotes: list[list[ArquivoDiff]] = []
        atual: list[ArquivoDiff] = []
        tamanho = 0
        for arquivo in arquivos:
            custo = len(arquivo.anotado()) + len(conteudos.get(arquivo.caminho_novo, ""))
            if atual and tamanho + custo > self._max_lote:
                lotes.append(atual)
                atual, tamanho = [], 0
            atual.append(arquivo)
            tamanho += custo
        if atual:
            lotes.append(atual)
        return lotes

    def _validar(
        self,
        sugeridos: list[ApontamentoSugerido],
        lote: list[ArquivoDiff],
        perfil: Perfil,
        revisao_id: int | None,
        guia_geral,
        guia_micro,
    ) -> tuple[list[Apontamento], int]:
        """Descarta linha inexistente no diff (alucinação), baixa confiança e duplicatas; verifica
        as fontes citadas pelo modelo (uma única consulta ao banco por lote)."""
        por_caminho = {a.caminho_novo: a for a in lote}
        todos_ids = [i for s in sugeridos for i in s.fontes_comentarios]
        existentes = {e.note_id for e in self._repo.obter_exemplos(perfil.nome, todos_ids)} if todos_ids else set()
        textos_guia = [g.conteudo for g in (guia_geral, guia_micro) if g]

        validos: list[Apontamento] = []
        vistos: set[tuple[str, int, str]] = set()
        descartados = 0
        for s in sugeridos:
            arquivo = por_caminho.get(s.arquivo)
            linha = arquivo.linha(s.linha) if arquivo else None
            chave = (s.arquivo, s.linha, s.comentario.lower())
            if linha is None or s.confianca < perfil.confianca_minima or chave in vistos:
                descartados += 1
                continue
            vistos.add(chave)
            fontes = verificar_fontes(
                comentarios_citados=list(s.fontes_comentarios),
                padrao_guia=s.fontes_padrao_guia,
                regra_perfil=s.fontes_regra_perfil,
                note_ids_existentes=existentes,
                textos_guia=textos_guia,
                instrucoes=perfil.instrucoes,
            )
            validos.append(
                Apontamento(
                    revisao_id=revisao_id or 0,
                    arquivo=arquivo.caminho_novo,
                    caminho_antigo=arquivo.caminho_antigo,
                    linha=s.linha,
                    linha_antiga=linha.linha_antiga if linha.tipo == " " else None,
                    severidade=s.severidade,
                    confianca=s.confianca,
                    texto_original=s.comentario,
                    trecho=arquivo.trecho(s.linha),
                    motivo=s.motivo,
                    fontes=fontes,
                )
            )
        return validos, descartados
