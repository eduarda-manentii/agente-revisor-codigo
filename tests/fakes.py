"""Dublês das portas externas. O banco é real (SQLite em pasta temporária)."""
from __future__ import annotations

import json
from typing import Iterator

from revisor.dominio.diff import ArquivoDiff, parse_hunks
from revisor.dominio.modelos import ComentarioHistorico, DadosMR, Perfil
from revisor.portas import Posicao

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


PERFIL_BACK = Perfil("back", "Java", (".java",), "instruções back", max_apontamentos=10, confianca_minima=5)
PERFIL_FRONT = Perfil("front", "Angular", (".ts",), "instruções front")
PERFIS = {"back": PERFIL_BACK, "front": PERFIL_FRONT}


class FakeGitLab:
    def __init__(self, mr: DadosMR | None = None, head_atual: str = "h1",
                 comentarios: list[ComentarioHistorico] | None = None,
                 falhar_em: set[int] | None = None) -> None:
        self.mr = mr or dados_mr(arquivo("src/ContratoService.java", DIFF_SERVICE))
        self.head_atual = head_atual
        self.comentarios = comentarios or []
        self.falhar_em = falhar_em or set()  # linhas cuja publicação deve falhar
        self.publicados: list[tuple[Posicao, str]] = []
        self.consultas_comentarios: list[tuple[str, str, str]] = []

    def obter_mr(self, projeto: str, iid: int) -> DadosMR:
        return self.mr

    def head_sha_atual(self, projeto: str, iid: int) -> str:
        return self.head_atual

    def criar_comentario(self, projeto: str, iid: int, posicao: Posicao, corpo: str) -> str:
        if posicao.linha_nova in self.falhar_em:
            raise RuntimeError("400 Bad Request: line_code inválido")
        self.publicados.append((posicao, corpo))
        return f"disc-{len(self.publicados)}"

    def listar_comentarios(self, projeto: str, autor: str, desde: str) -> Iterator[ComentarioHistorico]:
        self.consultas_comentarios.append((projeto, autor, desde))
        yield from (c for c in self.comentarios if c.projeto == projeto)


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


def sugestao(arquivo: str = "src/ContratoService.java", linha: int = 12, severidade: str = "P0",
             confianca: int = 8, comentario: str = "Status vindo do request: mass assignment.") -> dict:
    return {"arquivo": arquivo, "linha": linha, "severidade": severidade,
            "confianca": confianca, "comentario": comentario}
