import pytest

from revisor.dominio.risco import NivelRisco, arquivo_sensivel, classificar_risco


@pytest.mark.parametrize("linhas,arquivos,esperado", [
    (10, 20, NivelRisco.TRIVIAL),
    (11, 20, NivelRisco.LEVE),       # borda de linhas do trivial
    (10, 21, NivelRisco.COMPLETO),   # borda de arquivos do trivial (gap: não vira leve, vira completo)
    (100, 20, NivelRisco.LEVE),
    (101, 20, NivelRisco.COMPLETO),  # borda de linhas do leve
    (100, 21, NivelRisco.COMPLETO),  # borda de arquivos do leve
    (50, 50, NivelRisco.COMPLETO),
    (50, 51, NivelRisco.COMPLETO),
])
def test_bordas_da_classificacao(linhas, arquivos, esperado):
    assert classificar_risco(linhas, arquivos, algum_sensivel=False) == esperado


def test_arquivo_sensivel_forca_completo_mesmo_com_diff_minimo():
    assert classificar_risco(1, 1, algum_sensivel=True) == NivelRisco.COMPLETO


@pytest.mark.parametrize("caminho", [
    "src/auth/Login.java", "security/Token.ts", "crypto/Hash.java", "PermissionService.java",
    "src/token/Refresh.java", "config/senha.yml", "db/migrations/V1__init.sql",
])
def test_padroes_sensiveis_default(caminho):
    assert arquivo_sensivel(caminho) is True


def test_arquivo_comum_nao_e_sensivel():
    assert arquivo_sensivel("src/ContratoService.java") is False


def test_padroes_sensiveis_customizados():
    assert arquivo_sensivel("src/Pagamento.java", padroes=("pagamento",)) is True
    assert arquivo_sensivel("src/auth/Login.java", padroes=("pagamento",)) is False
