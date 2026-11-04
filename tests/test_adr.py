from revisor.dominio.adr import selecionar_arquivos_adr


def test_prefixo_configurado_filtra_so_a_pasta():
    caminhos = ["docs/adr/0001-x.md", "docs/adr/0002-y.md", "README.md", "docs/outra/0003-z.md"]
    assert selecionar_arquivos_adr(caminhos, "docs/adr") == ["docs/adr/0001-x.md", "docs/adr/0002-y.md"]


def test_autodeteccao_por_adr_no_caminho():
    caminhos = ["docs/ADR/decisao-1.md", "src/App.java", "README.md"]
    assert selecionar_arquivos_adr(caminhos) == ["docs/ADR/decisao-1.md"]


def test_autodeteccao_por_nome_numerado():
    caminhos = ["decisions/0007-usar-postgres.md", "decisions/outro.md", "README.md"]
    assert selecionar_arquivos_adr(caminhos) == ["decisions/0007-usar-postgres.md"]


def test_nada_encontrado_devolve_lista_vazia_sem_erro():
    assert selecionar_arquivos_adr(["README.md", "src/App.java"]) == []


def test_ignora_arquivos_nao_markdown_mesmo_sob_prefixo():
    caminhos = ["docs/adr/0001-x.md", "docs/adr/imagem.png"]
    assert selecionar_arquivos_adr(caminhos, "docs/adr") == ["docs/adr/0001-x.md"]
