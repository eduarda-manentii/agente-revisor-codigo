"""Pré-consolidação pura dos achados dos agentes especialistas (R4.1): agrupa o que parece ser o
mesmo problema, sem descartar nada — descarte é decisão do coordenador."""
from __future__ import annotations

from dataclasses import dataclass

from revisor.dominio.agentes import Achado
from revisor.dominio.heuristicas import tokens

_DISTANCIA_MAXIMA_LINHAS = 3
_SIMILARIDADE_MINIMA = 0.2


@dataclass(frozen=True)
class GrupoAchados:
    arquivo: str
    linha: int  # menor linha entre os achados do grupo
    achados: tuple[Achado, ...]

    @property
    def origens(self) -> tuple[str, ...]:
        vistas: list[str] = []
        for achado in self.achados:
            if achado.categoria not in vistas:
                vistas.append(achado.categoria)
        return tuple(vistas)


def _mesmo_problema(a: Achado, b: Achado) -> bool:
    if a.arquivo != b.arquivo or abs(a.linha - b.linha) > _DISTANCIA_MAXIMA_LINHAS:
        return False
    t1, t2 = tokens(a.comentario), tokens(b.comentario)
    uniao = t1 | t2
    jaccard = len(t1 & t2) / len(uniao) if uniao else 0.0
    return jaccard >= _SIMILARIDADE_MINIMA


def pre_consolidar(achados: list[Achado]) -> list[GrupoAchados]:
    """Agrupa achados do mesmo arquivo, a até 3 linhas de distância e com texto parecido (mesmo
    problema aparente). Nunca descarta: todo achado de entrada aparece em algum grupo de saída."""
    grupos: list[list[Achado]] = []
    for achado in achados:
        destino = next(
            (grupo for grupo in grupos if any(_mesmo_problema(achado, outro) for outro in grupo)), None
        )
        if destino is not None:
            destino.append(achado)
        else:
            grupos.append([achado])
    return [
        GrupoAchados(arquivo=g[0].arquivo, linha=min(a.linha for a in g), achados=tuple(g))
        for g in grupos
    ]
