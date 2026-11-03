"""Contrato do adaptador: payloads no formato da API de discussions/diffs do GitLab."""
from types import SimpleNamespace

from revisor.adaptadores.gitlab_adapter import GitLabAdapter
from revisor.portas import Posicao


class Gravador:
    def __init__(self):
        self.criados = []

    def create(self, dados):
        self.criados.append(dados)
        return SimpleNamespace(id="abc123")


def adaptador_com(projeto) -> GitLabAdapter:
    adaptador = GitLabAdapter("https://gitlab.empresa.com", "token")
    adaptador._projeto = lambda caminho: projeto  # isola a rede
    return adaptador


def test_posicao_de_linha_adicionada_nao_envia_old_line():
    discussions = Gravador()
    mr = SimpleNamespace(discussions=discussions)
    projeto = SimpleNamespace(mergerequests=SimpleNamespace(get=lambda iid, lazy=False: mr))
    pos = Posicao("b", "s", "h", "Antigo.java", "Novo.java", 12, None)
    assert adaptador_com(projeto).criar_comentario("g/p", 1, pos, "corpo") == "abc123"
    enviado = discussions.criados[0]
    assert enviado["body"] == "corpo"
    assert enviado["position"] == {
        "position_type": "text", "base_sha": "b", "start_sha": "s", "head_sha": "h",
        "old_path": "Antigo.java", "new_path": "Novo.java", "new_line": 12,
    }


def test_posicao_de_linha_de_contexto_envia_as_duas_linhas():
    discussions = Gravador()
    mr = SimpleNamespace(discussions=discussions)
    projeto = SimpleNamespace(mergerequests=SimpleNamespace(get=lambda iid, lazy=False: mr))
    adaptador_com(projeto).criar_comentario("g/p", 1, Posicao("b", "s", "h", "A", "A", 14, 12), "x")
    assert discussions.criados[0]["position"]["old_line"] == 12


def nota(id_, autor="fulana", tipo="DiffNote", sistema=False, **posicao):
    pos = {"new_path": "A.java", "new_line": 10, "head_sha": "h", "old_path": "A.java", "base_sha": "b"}
    pos.update(posicao)
    return {"id": id_, "type": tipo, "system": sistema, "body": f"comentário {id_}",
            "author": {"username": autor}, "position": pos, "resolved": False}


def test_listar_comentarios_filtra_autor_tipo_e_sistema_e_le_trecho():
    discussao = SimpleNamespace(attributes={"notes": [
        nota(1),
        nota(2, autor="outra"),
        nota(3, tipo=None),             # comentário geral, sem linha
        nota(4, sistema=True),
        nota(5, new_line=None, old_line=3),  # comentário em linha removida
    ]})
    discussao.attributes["notes"][1]["resolved"] = True  # thread resolvida por alguém
    mr = SimpleNamespace(iid=7, discussions=SimpleNamespace(list=lambda iterator: [discussao]))
    projeto = SimpleNamespace(id=1, mergerequests=SimpleNamespace(list=lambda **kw: [mr]))
    adaptador = adaptador_com(projeto)
    lidos = {}
    adaptador._arquivo_bruto = lambda pid, caminho, ref: lidos.setdefault(ref, tuple(f"l{i}" for i in range(1, 21)))

    comentarios = list(adaptador.listar_comentarios("g/p", "fulana", "2025-01-01"))

    assert [c.note_id for c in comentarios] == [1, 5]
    assert all(c.resolvido for c in comentarios)
    assert comentarios[0].linha == 10 and ">   10 l10" in comentarios[0].trecho
    assert comentarios[1].linha == 3 and set(lidos) == {"h", "b"}  # linha removida lê a versão base


def test_converte_diff_do_gitlab_em_arquivo():
    arq = GitLabAdapter._para_arquivo({
        "old_path": "a.java", "new_path": "b.java", "deleted_file": False,
        "diff": "@@ -1 +1 @@\n-x\n+y\n",
    })
    assert (arq.caminho_antigo, arq.caminho_novo, arq.removido) == ("a.java", "b.java", False)
    assert arq.linhas_comentaveis() == frozenset({1})
