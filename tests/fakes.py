"""Dublês das portas externas. O banco é real (SQLite em pasta temporária)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterator

from revisor.dominio.agentes import ResultadoAgente
from revisor.dominio.diff import ArquivoDiff, parse_hunks
from revisor.dominio.modelos import Agente, ComentarioHistorico, DadosMR, Perfil
from revisor.portas import ArvoreProjeto, EventoAgente, Posicao, ShaDivergente, Workspace, WorkspaceIndisponivel

DIFF_SERVICE = """\
@@ -10,4 +10,6 @@ public class ContratoService {
     public Contrato buscar(Long id) {
-        return repo.findById(id).get();
+        Contrato contrato = repo.findById(id).get();
+        contrato.setStatus(request.getStatus());
+        return contrato;
     }
"""

DIFF_COMPONENTE = """\
@@ -1,2 +1,3 @@
 export class ListaComponent {
+  dados: any;
 }
"""


def arquivo(caminho: str, diff: str, removido: bool = False) -> ArquivoDiff:
    return ArquivoDiff(caminho, caminho, parse_hunks(diff), removido)


def dados_mr(*arquivos: ArquivoDiff, head: str = "h1") -> DadosMR:
    return DadosMR("Ajusta contrato", "descrição", "b1", "s1", head, tuple(arquivos))


def comentario(
    projeto: str = "attornatus/microservicos/divida", mr_iid: int = 1, note_id: int = 1,
    arquivo: str = "src/ContratoService.java", linha: int | None = 12,
    comentario: str = "Status vindo do request: mass assignment, valide antes de setar.",
    resolvido: bool = False, autor: str = "fulano.silva", criado_em: str = "2025-01-01T10:00:00Z",
    trecho: str = "",
) -> ComentarioHistorico:
    return ComentarioHistorico(
        projeto=projeto, mr_iid=mr_iid, note_id=note_id, arquivo=arquivo, linha=linha,
        comentario=comentario, resolvido=resolvido, autor=autor, criado_em=criado_em,
        trecho=trecho or f"código em volta da linha {linha}",
    )


_AGENTES_POR_RISCO = {
    "TRIVIAL": ("qualidade",), "LEVE": ("qualidade",), "COMPLETO": ("qualidade",),
}
PERFIL_BACK = Perfil("back", "Java", (".java",), "instruções back", max_apontamentos=10,
                     agentes_por_risco=_AGENTES_POR_RISCO)
PERFIL_FRONT = Perfil("front", "Angular", (".ts",), "instruções front", agentes_por_risco=_AGENTES_POR_RISCO)
PERFIS = {"back": PERFIL_BACK, "front": PERFIL_FRONT}

AGENTE_QUALIDADE = Agente(nome="qualidade", instrucoes="instruções do agente qualidade")
AGENTES = {"qualidade": AGENTE_QUALIDADE}


class FakeGitLab:
    def __init__(
        self, mr: DadosMR | None = None, head_atual: str = "h1",
        comentarios: list[ComentarioHistorico] | None = None,
        falhar_em: set[int] | None = None,
        projetos_por_grupo: dict[str, list[str]] | None = None,
        grupos_invalidos: set[str] | None = None,
        falhar_coleta: set[str] | None = None,
        arvores: dict[str, ArvoreProjeto] | None = None,
        falhar_arvore: set[str] | None = None,
        conteudos_arquivo: dict[tuple[str, str, str], str] | None = None,
    ) -> None:
        self.mr = mr or dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE))
        self.head_atual = head_atual
        self.comentarios = comentarios or []
        self.falhar_em = falhar_em or set()  # linhas cuja publicação deve falhar
        self.projetos_por_grupo = projetos_por_grupo or {}
        self.grupos_invalidos = grupos_invalidos or set()
        self.falhar_coleta = falhar_coleta or set()  # projetos cuja coleta deve falhar
        self.arvores = arvores or {}
        self.falhar_arvore = falhar_arvore or set()
        self.conteudos_arquivo = conteudos_arquivo or {}
        self.publicados: list[tuple[Posicao, str]] = []
        self.consultas_comentarios: list[tuple[str, frozenset, str]] = []
        self.consultas_arquivo: list[tuple[str, str, str]] = []

    def obter_mr(self, projeto: str, iid: int) -> DadosMR:
        return self.mr

    def head_sha_atual(self, projeto: str, iid: int) -> str:
        return self.head_atual

    def criar_comentario(self, projeto: str, iid: int, posicao: Posicao, corpo: str) -> str:
        if posicao.linha_nova in self.falhar_em:
            raise RuntimeError("400 Bad Request: line_code inválido")
        self.publicados.append((posicao, corpo))
        return f"disc-{len(self.publicados)}"

    def listar_projetos(self, grupo: str) -> list[str]:
        if grupo in self.grupos_invalidos:
            raise RuntimeError(f"404 Group Not Found: {grupo}")
        return sorted(self.projetos_por_grupo.get(grupo, []))

    def listar_comentarios(
        self, projeto: str, desde: str, excluir_autores: set[str]
    ) -> Iterator[ComentarioHistorico]:
        self.consultas_comentarios.append((projeto, frozenset(excluir_autores), desde))
        if projeto in self.falhar_coleta:
            raise RuntimeError(f"403 Forbidden: sem permissão em {projeto}")
        yield from (c for c in self.comentarios if c.projeto == projeto and c.autor not in excluir_autores)

    def obter_arvore(self, projeto: str) -> ArvoreProjeto:
        if projeto in self.falhar_arvore:
            raise RuntimeError(f"projeto sem branch padrão: {projeto}")
        arvore = self.arvores.get(projeto)
        if arvore is None:
            raise KeyError(f"árvore não configurada para {projeto} no FakeGitLab")
        return arvore

    def obter_arquivo(self, projeto: str, caminho: str, ref: str) -> str | None:
        self.consultas_arquivo.append((projeto, caminho, ref))
        return self.conteudos_arquivo.get((projeto, caminho, ref))


class FakeWorkspace:
    """Dublê de PortaWorkspace. `arquivos` simula o conteúdo do checkout por caminho."""

    def __init__(
        self, arquivos: dict[str, str] | None = None,
        falhar_preparar: bool = False, sha_divergente: bool = False,
    ) -> None:
        self.arquivos = arquivos or {}
        self.falhar_preparar = falhar_preparar
        self.sha_divergente = sha_divergente
        self.contextos_escritos: list[tuple[Workspace, dict[str, str], str]] = []
        self.descartados: list[Workspace] = []

    def preparar(self, projeto: str, mr_iid: int, head_sha: str) -> Workspace:
        if self.falhar_preparar:
            raise WorkspaceIndisponivel("clone falhou (fake)")
        if self.sha_divergente:
            raise ShaDivergente("sha divergente (fake)")
        return Workspace(caminho=Path(f"/fake/{projeto}/{mr_iid}"), repo_cache=Path(f"/fake/cache/{projeto}"))

    def ler_arquivo(self, workspace: Workspace, caminho: str) -> str | None:
        return self.arquivos.get(caminho)

    def escrever_contexto(self, workspace: Workspace, patches: dict[str, str], contexto_md: str) -> None:
        self.contextos_escritos.append((workspace, patches, contexto_md))

    def descartar(self, workspace: Workspace) -> None:
        self.descartados.append(workspace)


class FakePortaAgente:
    """Dublê de PortaAgente. `respostas`: nome do agente -> ResultadoAgente (ou omitido = sucesso
    vazio). Registra concorrência de verdade (threads reais via ThreadPoolExecutor no caso de uso)."""

    def __init__(self, respostas: dict[str, ResultadoAgente] | None = None, atraso: float = 0.0) -> None:
        self.respostas = respostas or {}
        self.chamadas: list[str] = []
        self.usuarios: dict[str, str] = {}  # nome do agente -> último prompt de usuário recebido
        self.em_execucao = 0
        self.pico_concorrencia = 0
        self.atraso = atraso
        self._lock = threading.Lock()

    def executar(self, agente, workspace, modelo, usuario, ao_progresso):
        import time
        with self._lock:
            self.em_execucao += 1
            self.pico_concorrencia = max(self.pico_concorrencia, self.em_execucao)
            self.chamadas.append(agente.nome)
            self.usuarios[agente.nome] = usuario
        if self.atraso:
            time.sleep(self.atraso)
        ao_progresso(EventoAgente("tool_use", f"Lendo {agente.nome}.java"))
        resultado = self.respostas.get(agente.nome) or ResultadoAgente(agente=agente.nome, modelo_usado=modelo)
        with self._lock:
            self.em_execucao -= 1
        return resultado


def achado(
    arquivo: str = "src/ContratoService.java", linha: int = 12, severidade="P0", confianca: int = 8,
    categoria: str = "qualidade", comentario: str = "Status vindo do request: mass assignment.",
    evidencia: str = "trecho lido",
):
    from revisor.dominio.agentes import Achado
    from revisor.dominio.apontamento import Severidade
    sev = severidade if isinstance(severidade, Severidade) else Severidade(severidade)
    return Achado(arquivo=arquivo, linha=linha, severidade=sev, confianca=confianca,
                 categoria=categoria, comentario=comentario, evidencia=evidencia)


class FakeCoordenador:
    """Dublê de PortaCoordenador. Por padrão aprova todos os grupos citados no prompt (conta
    "## Grupo N" no texto recebido), com P1 genérico — dá pra customizar via `resposta`/`excecao`."""

    def __init__(self, resposta: str | None = None, excecao: Exception | None = None) -> None:
        self.resposta = resposta
        self.excecao = excecao
        self.chamadas: list[tuple[str, str]] = []

    def executar(self, workspace, modelo, sistema, usuario, ao_progresso):
        import re
        self.chamadas.append((sistema, usuario))
        ao_progresso(EventoAgente("tool_use", "Lendo A.java"))
        if self.excecao is not None:
            raise self.excecao
        if self.resposta is not None:
            return self.resposta
        indices = [int(m) for m in re.findall(r"## Grupo (\d+)", usuario)]
        apontamentos = [
            {"grupo": i, "severidade": "P1", "comentario": f"Reescrito pelo coordenador (grupo {i})"}
            for i in indices
        ]
        return json.dumps({"apontamentos": apontamentos, "descartados": [], "resumo": "resumo de teste"})


class FakeLLM:
    """Devolve respostas roteirizadas, em ordem, e grava o que recebeu."""

    def __init__(self, *respostas: str | list) -> None:
        self.respostas = [r if isinstance(r, str) else json.dumps(r) for r in respostas]
        self.chamadas: list[tuple[str, str]] = []

    def completar(self, sistema: str, usuario: str) -> str:
        self.chamadas.append((sistema, usuario))
        if not self.respostas:
            raise AssertionError("FakeLLM chamado mais vezes do que o roteiro previa")
        return self.respostas.pop(0)


def sugestao(
    arquivo: str = "src/ContratoService.java", linha: int = 12, severidade: str = "P0",
    confianca: int = 8, comentario: str = "Status vindo do request: mass assignment.",
    motivo: str = "", fontes: dict | None = None,
) -> dict:
    item = {"arquivo": arquivo, "linha": linha, "severidade": severidade,
            "confianca": confianca, "comentario": comentario}
    if motivo:
        item["motivo"] = motivo
    if fontes is not None:
        item["fontes"] = fontes
    return item
