"""Contrato do adaptador: payloads no formato da API de discussions/diffs/árvore do GitLab."""
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
            "author": {"username": autor}, "position": pos, "resolved": False,
            "created_at": "2025-06-01T10:00:00Z"}


def test_listar_comentarios_filtra_autor_do_mr_excluidos_tipo_e_sistema_e_le_trecho():
    discussao = SimpleNamespace(attributes={"notes": [
        nota(1),                        # válido
        nota(2, autor="autor_do_mr"),    # é o próprio autor do MR respondendo
        nota(3, autor="bot"),            # está em excluir_autores
        nota(4, tipo=None),              # comentário geral, sem linha
        nota(5, sistema=True),
        nota(6, new_line=None, old_line=3),  # comentário em linha removida
    ]})
    discussao.attributes["notes"][0]["resolved"] = True  # thread resolvida por alguém
    mr = SimpleNamespace(
        iid=7, author={"username": "autor_do_mr"},
        discussions=SimpleNamespace(list=lambda iterator: [discussao]),
    )
    projeto = SimpleNamespace(id=1, mergerequests=SimpleNamespace(list=lambda **kw: [mr]))
    adaptador = adaptador_com(projeto)
    lidos = {}
    adaptador._ler_arquivo = lambda pid, caminho, ref: lidos.setdefault(
        ref, "\n".join(f"l{i}" for i in range(1, 21))
    )

    comentarios = list(adaptador.listar_comentarios("g/p", "2025-01-01", {"bot"}))

    assert [c.note_id for c in comentarios] == [1, 6]
    assert comentarios[0].resolvido and comentarios[0].autor == "fulana"
    assert comentarios[0].criado_em == "2025-06-01T10:00:00Z"
    assert comentarios[0].linha == 10 and ">   10 l10" in comentarios[0].trecho
    assert comentarios[1].linha == 3 and set(lidos) == {"h", "b"}  # linha removida lê a versão base


def test_converte_diff_do_gitlab_em_arquivo():
    arq = GitLabAdapter._para_arquivo({
        "old_path": "a.java", "new_path": "b.java", "deleted_file": False,
        "diff": "@@ -1 +1 @@\n-x\n+y\n",
    })
    assert (arq.caminho_antigo, arq.caminho_novo, arq.removido) == ("a.java", "b.java", False)
    assert arq.linhas_comentaveis() == frozenset({1})


def test_listar_projetos_devolve_path_with_namespace_em_ordem_alfabetica():
    projetos = [SimpleNamespace(path_with_namespace="g/micros/zulu"),
                SimpleNamespace(path_with_namespace="g/micros/alfa")]
    grupo = SimpleNamespace(projects=SimpleNamespace(
        list=lambda **kw: projetos if kw.get("include_subgroups") and kw.get("archived") is False else []
    ))
    adaptador = GitLabAdapter("https://gitlab.empresa.com", "token")
    adaptador._gl.groups = SimpleNamespace(get=lambda nome: grupo if nome == "g/micros" else (_ for _ in ()).throw(
        Exception("404 Group Not Found")
    ))
    assert adaptador.listar_projetos("g/micros") == ["g/micros/alfa", "g/micros/zulu"]


def test_obter_arvore_usa_branch_padrao_e_filtra_so_blobs():
    projeto = SimpleNamespace(
        default_branch="main",
        branches=SimpleNamespace(get=lambda nome: SimpleNamespace(commit={"id": "sha123"})),
        repository_tree=lambda **kw: [
            {"path": "src/A.java", "type": "blob"},
            {"path": "src", "type": "tree"},
        ] if kw.get("ref") == "sha123" and kw.get("recursive") else [],
    )
    adaptador = adaptador_com(projeto)
    arvore = adaptador.obter_arvore("g/p")
    assert arvore.sha == "sha123"
    assert arvore.caminhos == ("src/A.java",)


def test_obter_arquivo_devolve_conteudo_decodificado():
    class Gl:
        def __init__(self):
            self.projects = SimpleNamespace(
                get=lambda pid, lazy=True: SimpleNamespace(
                    files=SimpleNamespace(raw=lambda file_path, ref: b"conteudo do arquivo")
                )
            )

    projeto = SimpleNamespace(id=42)
    adaptador = adaptador_com(projeto)
    adaptador._gl = Gl()
    assert adaptador.obter_arquivo("g/p", "A.java", "sha1") == "conteudo do arquivo"
