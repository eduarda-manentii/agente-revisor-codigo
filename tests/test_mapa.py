from revisor.dominio.mapa import excluido, selecionar_arquivos_mapa


def test_nunca_seleciona_config_segredo_teste_dependencia_ou_binario():
    caminhos = [
        "src/main/resources/application.yml",
        "src/main/resources/application-prod.properties",
        "bootstrap.yml",
        ".env.local",
        "src/main/java/com/x/SecretManager.java",
        "src/main/java/com/x/CredentialStore.java",
        "certs/chave.pem",
        "certs/chave.jks",
        "src/test/java/com/x/ContratoServiceTest.java",
        "src/main/java/com/x/ContratoServiceTests.java",
        "src/main/java/com/x/ContratoServiceIT.java",
        "front/src/app/x.spec.ts",
        "node_modules/pacote/index.js",
        "target/classes/X.class",
        "dist/main.js",
        "build/libs/app.jar",
        ".git/HEAD",
        "coverage/lcov.info",
        "logo.png",  # extensão não permitida
    ]
    selecionados = selecionar_arquivos_mapa(caminhos)
    assert selecionados == []
    for c in caminhos:
        assert excluido(c) or not c.lower().endswith(
            (".java", ".kt", ".ts", ".xml", ".json", ".md", ".gradle", ".sql")
        )


def test_seleciona_manifesto_base_compartilhado_e_camadas_respeitando_teto():
    caminhos = [
        "pom.xml",
        "README.md",
        "src/main/java/com/x/base/BaseService.java",
        "src/main/java/com/x/base/AbstractRepository.java",
        "src/main/java/com/x/shared/Util1.java",
        "src/main/java/com/x/shared/Util2.java",
        "src/main/java/com/x/ContratoController.java",
        "src/main/java/com/x/ContratoService.java",
        "src/main/java/com/x/ContratoServiceImpl.java",
        "src/main/java/com/x/ContratoRepository.java",
        "src/main/java/com/x/PagamentoConsumer.java",
        "src/main/java/com/x/ContratoMapper.java",
        "src/main/java/com/x/irrelevante/Outro.java",
    ]
    selecionados = selecionar_arquivos_mapa(caminhos, max_arquivos=30)
    assert "pom.xml" in selecionados
    assert "README.md" in selecionados
    assert "src/main/java/com/x/base/BaseService.java" in selecionados
    assert "src/main/java/com/x/shared/Util1.java" in selecionados
    assert "src/main/java/com/x/ContratoController.java" in selecionados
    assert "src/main/java/com/x/ContratoServiceImpl.java" in selecionados
    assert "src/main/java/com/x/ContratoRepository.java" in selecionados
    assert "src/main/java/com/x/PagamentoConsumer.java" in selecionados
    assert "src/main/java/com/x/ContratoMapper.java" in selecionados


def test_respeita_teto_maximo_de_arquivos():
    caminhos = [f"src/main/java/com/x/shared/Util{i}.java" for i in range(20)]
    assert len(selecionar_arquivos_mapa(caminhos, max_arquivos=5)) == 5


def test_mais_rasos_e_curtos_primeiro_dentro_da_categoria():
    caminhos = [
        "src/main/java/com/x/y/z/shared/UtilLongoDemais.java",
        "src/main/java/shared/Util.java",
    ]
    selecionados = selecionar_arquivos_mapa(caminhos, max_arquivos=1)
    assert selecionados == ["src/main/java/shared/Util.java"]
