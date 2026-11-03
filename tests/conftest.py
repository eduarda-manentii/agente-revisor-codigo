import pytest

from revisor.adaptadores.banco import RepositorioSQLite


@pytest.fixture
def repo(tmp_path):
    return RepositorioSQLite(tmp_path / "teste.db")
