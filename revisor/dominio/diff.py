"""Parse de unified diff e regras de 'linha comentável' no GitLab."""
from __future__ import annotations

import re
from dataclasses import dataclass

_CABECALHO_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class LinhaDiff:
    tipo: str  # "+", "-" ou " "
    texto: str
    linha_antiga: int | None
    linha_nova: int | None


@dataclass(frozen=True)
class ArquivoDiff:
    caminho_antigo: str
    caminho_novo: str
    linhas: tuple[LinhaDiff, ...]
    removido: bool = False

    def linhas_comentaveis(self) -> frozenset[int]:
        """Linhas do lado novo (adicionadas ou de contexto): onde o comentário é permitido."""
        return frozenset(l.linha_nova for l in self.linhas if l.linha_nova is not None)

    def linha(self, numero_novo: int) -> LinhaDiff | None:
        return next((l for l in self.linhas if l.linha_nova == numero_novo), None)

    def texto_adicionado(self) -> str:
        return "\n".join(l.texto for l in self.linhas if l.tipo == "+")

    def anotado(self) -> str:
        """Diff com o número da linha nova à esquerda, para o LLM citar linhas reais."""
        saida = [f"### arquivo: {self.caminho_novo}"]
        for l in self.linhas:
            numero = f"{l.linha_nova:>5}" if l.linha_nova is not None else " " * 5
            saida.append(f"{numero} {l.tipo} | {l.texto}")
        return "\n".join(saida)

    def trecho(self, numero_novo: int, contexto: int = 3) -> str:
        """Trecho em volta da linha, com a linha alvo marcada por '>'."""
        indice = next((i for i, l in enumerate(self.linhas) if l.linha_nova == numero_novo), None)
        if indice is None:
            return ""
        janela = self.linhas[max(0, indice - contexto): indice + contexto + 1]
        saida = []
        for l in janela:
            marca = ">" if l.linha_nova == numero_novo else " "
            numero = f"{l.linha_nova:>5}" if l.linha_nova is not None else " " * 5
            saida.append(f"{marca}{numero} {l.tipo} {l.texto}")
        return "\n".join(saida)


def parse_hunks(diff: str) -> tuple[LinhaDiff, ...]:
    linhas: list[LinhaDiff] = []
    antiga = nova = 0
    dentro_de_hunk = False
    for bruta in diff.splitlines():
        cabecalho = _CABECALHO_HUNK.match(bruta)
        if cabecalho:
            antiga, nova = int(cabecalho.group(1)), int(cabecalho.group(2))
            dentro_de_hunk = True
            continue
        if not dentro_de_hunk or bruta.startswith("\\"):  # "\ No newline at end of file"
            continue
        prefixo, texto = (bruta[:1] or " "), bruta[1:]
        if prefixo == "+":
            linhas.append(LinhaDiff("+", texto, None, nova))
            nova += 1
        elif prefixo == "-":
            linhas.append(LinhaDiff("-", texto, antiga, None))
            antiga += 1
        else:
            linhas.append(LinhaDiff(" ", texto, antiga, nova))
            antiga += 1
            nova += 1
    return tuple(linhas)
