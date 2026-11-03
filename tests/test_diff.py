from revisor.dominio.diff import parse_hunks
from tests.fakes import DIFF_SERVICE, arquivo


def test_parse_numera_lados_novo_e_antigo():
    linhas = parse_hunks(DIFF_SERVICE)
    contexto, removida, *adicionadas, fim = linhas
    assert (contexto.tipo, contexto.linha_antiga, contexto.linha_nova) == (" ", 10, 10)
    assert (removida.tipo, removida.linha_antiga, removida.linha_nova) == ("-", 11, None)
    assert [l.linha_nova for l in adicionadas] == [11, 12, 13]
    assert (fim.linha_antiga, fim.linha_nova) == (12, 14)


def test_linha_removida_nao_e_comentavel():
    arq = arquivo("A.java", DIFF_SERVICE)
    assert arq.linhas_comentaveis() == frozenset({10, 11, 12, 13, 14})


def test_ignora_marcador_sem_quebra_de_linha_e_multiplos_hunks():
    diff = "@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n@@ -50,1 +50,2 @@\n x\n+y\n"
    novas = [l.linha_nova for l in parse_hunks(diff) if l.linha_nova]
    assert novas == [1, 50, 51]


def test_diff_vazio_ou_binario_nao_quebra():
    assert parse_hunks("") == ()
    assert parse_hunks("Binary files differ") == ()


def test_anotado_mostra_numero_so_no_lado_novo():
    anotado = arquivo("A.java", DIFF_SERVICE).anotado()
    assert "### arquivo: A.java" in anotado
    assert "   12 + |         contrato.setStatus(request.getStatus());" in anotado
    assert "      - |         return repo.findById(id).get();" in anotado


def test_trecho_marca_linha_alvo_e_respeita_bordas():
    trecho = arquivo("A.java", DIFF_SERVICE).trecho(12, contexto=1)
    linhas = trecho.splitlines()
    assert len(linhas) == 3
    assert linhas[1].startswith(">   12 +")
    assert arquivo("A.java", DIFF_SERVICE).trecho(999) == ""
