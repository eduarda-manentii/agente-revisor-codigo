"""Repositório SQLite. Uma conexão por operação: seguro para tarefas em background."""
from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from revisor.dominio.apontamento import Apontamento, MotivoRejeicao, Severidade, Status
from revisor.dominio.coordenador import Descarte
from revisor.dominio.fontes import Fontes
from revisor.dominio.modelos import (
    GERAL,
    EventoRevisao,
    ExecucaoAgente,
    Exemplo,
    Guia,
    GuiaArquitetura,
    MapaProjeto,
    Revisao,
    StatusExecucao,
    Treino,
)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS revisoes (
    id INTEGER PRIMARY KEY, mr_url TEXT NOT NULL, projeto TEXT NOT NULL, mr_iid INTEGER NOT NULL,
    perfil TEXT NOT NULL, status TEXT NOT NULL, titulo_mr TEXT, base_sha TEXT, start_sha TEXT,
    head_sha TEXT, guia_versao INTEGER, guia_micro_versao INTEGER, mapa_em TEXT,
    descartados INTEGER DEFAULT 0, nota TEXT, resumo_coordenador TEXT, erro TEXT, etapa TEXT, etapa_iniciada_em TEXT,
    atualizado_em TEXT, nivel_risco TEXT, arquivos_ignorados TEXT, workspace_aviso TEXT,
    criada_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_versao (
    versao INTEGER PRIMARY KEY, aplicada_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos_revisao (
    id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
    etapa TEXT NOT NULL, criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_revisao ON eventos_revisao(revisao_id);
CREATE TABLE IF NOT EXISTS apontamentos (
    id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
    arquivo TEXT NOT NULL, caminho_antigo TEXT NOT NULL, linha INTEGER NOT NULL,
    linha_antiga INTEGER, severidade TEXT NOT NULL, confianca INTEGER NOT NULL,
    texto_original TEXT NOT NULL, trecho TEXT, texto_final TEXT NOT NULL, status TEXT NOT NULL,
    motivo_rejeicao TEXT, discussion_id TEXT, erro TEXT, motivo TEXT, fontes TEXT,
    origens TEXT, incorporado_versao INTEGER
);
CREATE INDEX IF NOT EXISTS ix_apontamentos_revisao ON apontamentos(revisao_id);
CREATE TABLE IF NOT EXISTS treinos (
    id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, completo INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, novos_exemplos INTEGER DEFAULT 0, guia_versao INTEGER, avisos TEXT,
    progresso TEXT, erro TEXT, iniciado_em TEXT NOT NULL, concluido_em TEXT
);
CREATE TABLE IF NOT EXISTS exemplos (
    id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, projeto TEXT NOT NULL, mr_iid INTEGER NOT NULL,
    note_id INTEGER NOT NULL, arquivo TEXT NOT NULL, linha INTEGER, trecho TEXT,
    comentario TEXT NOT NULL, resolvido INTEGER NOT NULL, autor TEXT, criado_em TEXT,
    incorporado_versao INTEGER, incorporado_projeto_versao INTEGER,
    UNIQUE (perfil, note_id)
);
CREATE INDEX IF NOT EXISTS ix_exemplos_perfil_projeto ON exemplos(perfil, projeto);
CREATE TABLE IF NOT EXISTS checkpoints (
    perfil TEXT NOT NULL, projeto TEXT NOT NULL, desde TEXT NOT NULL, PRIMARY KEY (perfil, projeto)
);
CREATE TABLE IF NOT EXISTS guias (
    id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, escopo TEXT NOT NULL, versao INTEGER NOT NULL,
    conteudo TEXT NOT NULL, exemplos_usados INTEGER NOT NULL, criado_em TEXT NOT NULL,
    UNIQUE (perfil, escopo, versao)
);
CREATE TABLE IF NOT EXISTS mapas (
    id INTEGER PRIMARY KEY, projeto TEXT NOT NULL, sha TEXT NOT NULL, conteudo TEXT NOT NULL,
    arquivos_lidos TEXT NOT NULL, criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mapas_projeto ON mapas(projeto);
CREATE TABLE IF NOT EXISTS agentes_execucao (
    id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
    agente TEXT NOT NULL, estado TEXT NOT NULL, etapa TEXT, modelo TEXT,
    tokens_entrada INTEGER DEFAULT 0, tokens_saida INTEGER DEFAULT 0,
    achados_validos INTEGER DEFAULT 0, achados_descartados INTEGER DEFAULT 0, resposta_bruta TEXT,
    iniciado_em TEXT, atualizado_em TEXT,
    UNIQUE (revisao_id, agente)
);
CREATE INDEX IF NOT EXISTS ix_agentes_execucao_revisao ON agentes_execucao(revisao_id);
CREATE TABLE IF NOT EXISTS descartes_coordenacao (
    id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
    arquivo TEXT NOT NULL, linha INTEGER NOT NULL, severidade TEXT NOT NULL,
    confianca INTEGER NOT NULL, comentario TEXT NOT NULL, evidencia TEXT, motivo TEXT NOT NULL,
    origens TEXT, recuperado INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_descartes_coordenacao_revisao ON descartes_coordenacao(revisao_id);
CREATE TABLE IF NOT EXISTS guia_arquitetura (
    id INTEGER PRIMARY KEY, projeto_fonte TEXT NOT NULL, sha TEXT NOT NULL, conteudo TEXT NOT NULL,
    arquivos_lidos TEXT NOT NULL, criado_em TEXT NOT NULL
);
"""

# Colunas acrescentadas depois da primeira versão: bancos antigos recebem ALTER TABLE.
_MIGRACOES = [
    ("apontamentos", "incorporado_versao", "INTEGER"),
    ("exemplos", "incorporado_versao", "INTEGER"),
    ("treinos", "completo", "INTEGER NOT NULL DEFAULT 0"),
    ("exemplos", "autor", "TEXT"),
    ("exemplos", "criado_em", "TEXT"),
    ("exemplos", "incorporado_projeto_versao", "INTEGER"),
    ("apontamentos", "motivo", "TEXT"),
    ("apontamentos", "fontes", "TEXT"),
    ("treinos", "avisos", "TEXT"),
    ("revisoes", "guia_micro_versao", "INTEGER"),
    ("revisoes", "mapa_em", "TEXT"),
    ("revisoes", "etapa", "TEXT"),
    ("revisoes", "etapa_iniciada_em", "TEXT"),
    ("revisoes", "atualizado_em", "TEXT"),
]

# A partir daqui, migrações novas entram aqui: cada uma roda uma única vez (controlada pela tabela
# schema_versao), em vez do padrão ad-hoc de _MIGRACOES acima.
_MIGRACOES_VERSIONADAS: list[tuple[int, str]] = [
    (1, "ALTER TABLE revisoes ADD COLUMN nivel_risco TEXT"),
    (2, "ALTER TABLE revisoes ADD COLUMN arquivos_ignorados TEXT"),
    (3, "ALTER TABLE revisoes ADD COLUMN workspace_aviso TEXT"),
    (4, """
        CREATE TABLE IF NOT EXISTS agentes_execucao (
            id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
            agente TEXT NOT NULL, estado TEXT NOT NULL, etapa TEXT, modelo TEXT,
            tokens_entrada INTEGER DEFAULT 0, tokens_saida INTEGER DEFAULT 0,
            iniciado_em TEXT, atualizado_em TEXT,
            UNIQUE (revisao_id, agente)
        )
    """),
    (5, "CREATE INDEX IF NOT EXISTS ix_agentes_execucao_revisao ON agentes_execucao(revisao_id)"),
    (6, "ALTER TABLE apontamentos ADD COLUMN origens TEXT"),
    (7, """
        CREATE TABLE IF NOT EXISTS descartes_coordenacao (
            id INTEGER PRIMARY KEY, revisao_id INTEGER NOT NULL REFERENCES revisoes(id),
            arquivo TEXT NOT NULL, linha INTEGER NOT NULL, severidade TEXT NOT NULL,
            confianca INTEGER NOT NULL, comentario TEXT NOT NULL, evidencia TEXT, motivo TEXT NOT NULL,
            origens TEXT, recuperado INTEGER NOT NULL DEFAULT 0
        )
    """),
    (8, "CREATE INDEX IF NOT EXISTS ix_descartes_coordenacao_revisao ON descartes_coordenacao(revisao_id)"),
    (9, """
        CREATE TABLE IF NOT EXISTS guia_arquitetura (
            id INTEGER PRIMARY KEY, projeto_fonte TEXT NOT NULL, sha TEXT NOT NULL,
            conteudo TEXT NOT NULL, arquivos_lidos TEXT NOT NULL, criado_em TEXT NOT NULL
        )
    """),
    (10, "ALTER TABLE agentes_execucao ADD COLUMN achados_validos INTEGER DEFAULT 0"),
    (11, "ALTER TABLE agentes_execucao ADD COLUMN achados_descartados INTEGER DEFAULT 0"),
    (12, "ALTER TABLE agentes_execucao ADD COLUMN resposta_bruta TEXT"),
    (13, "ALTER TABLE revisoes ADD COLUMN resumo_coordenador TEXT"),
]

_CAMPOS_APONTAMENTO = [f.name for f in fields(Apontamento) if f.name != "id"]
_CAMPOS_REVISAO = [f.name for f in fields(Revisao) if f.name != "id"]
_CAMPOS_TREINO = [f.name for f in fields(Treino) if f.name != "id"]
_CAMPOS_EXECUCAO_AGENTE = [f.name for f in fields(ExecucaoAgente) if f.name != "id"]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fontes_de_json(valor: str | None) -> Fontes:
    if valor is None:
        return Fontes(registrada=False)
    dados = json.loads(valor)
    return Fontes(
        comentarios=tuple(dados.get("comentarios", [])),
        comentarios_nao_confirmados=tuple(dados.get("comentarios_nao_confirmados", [])),
        padrao_guia=dados.get("padrao_guia", ""),
        padrao_confirmado=bool(dados.get("padrao_confirmado", False)),
        regra_perfil=dados.get("regra_perfil", ""),
        regra_confirmada=bool(dados.get("regra_confirmada", False)),
        registrada=True,
    )


class NaoEncontrado(LookupError):
    pass


class RepositorioSQLite:
    def __init__(self, caminho: Path) -> None:
        self._caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conexao() as con:
            nova_instalacao = not self._tabela_existe(con, "revisoes")
            fazer_backup = not nova_instalacao and (
                self._migracao_legada_pendente(con) or self._migracao_versionada_pendente(con)
            )
        if fazer_backup:
            self._fazer_backup()
        with self._conexao() as con:
            self._migrar_guias_para_escopo(con)
            con.executescript(_ESQUEMA)
            for tabela, coluna, tipo in _MIGRACOES:
                existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
                if coluna not in existentes:
                    con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            self._aplicar_migracoes_versionadas(con)

    def _fazer_backup(self) -> None:
        """Copia o banco inteiro antes de migrar, pra nunca depender só da migração ter dado certo."""
        if not self._caminho.exists() or self._caminho.stat().st_size == 0:
            return
        pasta_backup = self._caminho.parent / "backup"
        pasta_backup.mkdir(parents=True, exist_ok=True)
        marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destino = pasta_backup / f"{self._caminho.stem}-{marca}{self._caminho.suffix}"
        shutil.copy2(self._caminho, destino)

    @staticmethod
    def _tabela_existe(con: sqlite3.Connection, nome: str) -> bool:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (nome,)
        ).fetchone() is not None

    @staticmethod
    def _migracao_legada_pendente(con: sqlite3.Connection) -> bool:
        for tabela, coluna, _ in _MIGRACOES:
            if not RepositorioSQLite._tabela_existe(con, tabela):
                continue
            existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
            if coluna not in existentes:
                return True
        return False

    @staticmethod
    def _migracao_versionada_pendente(con: sqlite3.Connection) -> bool:
        if not RepositorioSQLite._tabela_existe(con, "schema_versao"):
            return True
        aplicadas = {r[0] for r in con.execute("SELECT versao FROM schema_versao")}
        return any(versao not in aplicadas for versao, _ in _MIGRACOES_VERSIONADAS)

    @staticmethod
    def _aplicar_migracoes_versionadas(con: sqlite3.Connection) -> None:
        """Cada migração roda uma única vez, registrada em schema_versao. O SQL (ALTER TABLE ADD
        COLUMN ou CREATE TABLE/INDEX IF NOT EXISTS) já pode ter efeito mesmo sem ter sido marcado
        como aplicado ainda — ex.: tabela/coluna nasceu agora pelo _ESQUEMA atual, mas outra tabela
        da mesma instalação é antiga. Por isso tenta rodar e ignora "coluna duplicada": é só o sinal
        de que já estava lá."""
        aplicadas = {r[0] for r in con.execute("SELECT versao FROM schema_versao")}
        for versao, sql in _MIGRACOES_VERSIONADAS:
            if versao in aplicadas:
                continue
            try:
                con.execute(sql)
            except sqlite3.OperationalError as erro:
                if "duplicate column name" not in str(erro):
                    raise
            con.execute(
                "INSERT INTO schema_versao (versao, aplicada_em) VALUES (?, ?)", (versao, _agora())
            )

    @staticmethod
    def _migrar_guias_para_escopo(con: sqlite3.Connection) -> None:
        """guias antigas não tinham `escopo`; a chave única era (perfil, versao). Como o SQLite não
        altera restrição, reconstrói a tabela e marca tudo que já existia como o guia GERAL."""
        tabelas = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "guias" not in tabelas:
            return
        colunas = {r["name"] for r in con.execute("PRAGMA table_info(guias)")}
        if "escopo" in colunas:
            return
        con.executescript(
            "CREATE TABLE guias_nova ("
            "id INTEGER PRIMARY KEY, perfil TEXT NOT NULL, escopo TEXT NOT NULL, versao INTEGER NOT NULL, "
            "conteudo TEXT NOT NULL, exemplos_usados INTEGER NOT NULL, criado_em TEXT NOT NULL, "
            "UNIQUE (perfil, escopo, versao));"
            "INSERT INTO guias_nova (id, perfil, escopo, versao, conteudo, exemplos_usados, criado_em) "
            f"SELECT id, perfil, '{GERAL}', versao, conteudo, exemplos_usados, criado_em FROM guias;"
            "DROP TABLE guias;"
            "ALTER TABLE guias_nova RENAME TO guias;"
        )

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self._caminho, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:  # commit/rollback automático
                yield con
        finally:
            con.close()

    def _um(self, sql: str, parametros: tuple) -> sqlite3.Row:
        with self._conexao() as con:
            linha = con.execute(sql, parametros).fetchone()
        if linha is None:
            raise NaoEncontrado(f"Registro não encontrado: {parametros}")
        return linha

    # ---------- revisões ----------
    @staticmethod
    def _para_revisao(r: sqlite3.Row) -> Revisao:
        dados = dict(r)
        dados["status"] = StatusExecucao(dados["status"])
        excecoes = ("guia_versao", "guia_micro_versao")
        return Revisao(**{k: ("" if v is None and k not in excecoes else v) for k, v in dados.items()})

    def criar_revisao(self, revisao: Revisao) -> int:
        revisao.criada_em = revisao.criada_em or _agora()
        valores = asdict(revisao)
        with self._conexao() as con:
            cursor = con.execute(
                f"INSERT INTO revisoes ({', '.join(_CAMPOS_REVISAO)}) "
                f"VALUES ({', '.join('?' for _ in _CAMPOS_REVISAO)})",
                tuple(valores[c] for c in _CAMPOS_REVISAO),
            )
            revisao.id = cursor.lastrowid
        return revisao.id

    def salvar_revisao(self, revisao: Revisao) -> None:
        valores = asdict(revisao)
        with self._conexao() as con:
            con.execute(
                f"UPDATE revisoes SET {', '.join(f'{c} = ?' for c in _CAMPOS_REVISAO)} WHERE id = ?",
                tuple(valores[c] for c in _CAMPOS_REVISAO) + (revisao.id,),
            )

    def obter_revisao(self, revisao_id: int) -> Revisao:
        return self._para_revisao(self._um("SELECT * FROM revisoes WHERE id = ?", (revisao_id,)))

    def listar_revisoes(self, limite: int = 30) -> list[Revisao]:
        with self._conexao() as con:
            linhas = con.execute("SELECT * FROM revisoes ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [self._para_revisao(r) for r in linhas]

    def obter_revisao_anterior(self, projeto: str, mr_iid: int, antes_de: int) -> Revisao | None:
        with self._conexao() as con:
            linha = con.execute(
                "SELECT * FROM revisoes WHERE projeto = ? AND mr_iid = ? AND id < ? AND status = 'CONCLUIDA' "
                "ORDER BY id DESC LIMIT 1",
                (projeto, mr_iid, antes_de),
            ).fetchone()
        return self._para_revisao(linha) if linha else None

    # ---------- apontamentos ----------
    @staticmethod
    def _valores_apontamento(ap: Apontamento) -> dict:
        valores = asdict(ap)
        valores["fontes"] = json.dumps(valores["fontes"]) if valores["fontes"] is not None else None
        return valores

    @staticmethod
    def _para_apontamento(r: sqlite3.Row) -> Apontamento:
        dados = dict(r)
        dados.pop("incorporado_versao", None)
        dados["severidade"] = Severidade(dados["severidade"])
        dados["status"] = Status(dados["status"])
        if dados["motivo_rejeicao"]:
            dados["motivo_rejeicao"] = MotivoRejeicao(dados["motivo_rejeicao"])
        dados["trecho"] = dados["trecho"] or ""
        dados["motivo"] = dados["motivo"] or ""
        dados["origens"] = dados["origens"] or ""
        dados["fontes"] = _fontes_de_json(dados["fontes"])
        return Apontamento(**dados)

    def adicionar_apontamentos(self, apontamentos: list[Apontamento]) -> None:
        with self._conexao() as con:
            for ap in apontamentos:
                valores = self._valores_apontamento(ap)
                cursor = con.execute(
                    f"INSERT INTO apontamentos ({', '.join(_CAMPOS_APONTAMENTO)}) "
                    f"VALUES ({', '.join('?' for _ in _CAMPOS_APONTAMENTO)})",
                    tuple(valores[c] for c in _CAMPOS_APONTAMENTO),
                )
                ap.id = cursor.lastrowid

    def salvar_apontamento(self, apontamento: Apontamento) -> None:
        valores = self._valores_apontamento(apontamento)
        with self._conexao() as con:
            con.execute(
                f"UPDATE apontamentos SET {', '.join(f'{c} = ?' for c in _CAMPOS_APONTAMENTO)} WHERE id = ?",
                tuple(valores[c] for c in _CAMPOS_APONTAMENTO) + (apontamento.id,),
            )

    def obter_apontamento(self, apontamento_id: int) -> Apontamento:
        return self._para_apontamento(
            self._um("SELECT * FROM apontamentos WHERE id = ?", (apontamento_id,))
        )

    def listar_apontamentos(self, revisao_id: int) -> list[Apontamento]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT * FROM apontamentos WHERE revisao_id = ? ORDER BY arquivo, linha", (revisao_id,)
            ).fetchall()
        return [self._para_apontamento(r) for r in linhas]

    def listar_rejeitados_pendentes(self, perfil: str) -> list[Apontamento]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT a.* FROM apontamentos a JOIN revisoes r ON r.id = a.revisao_id "
                "WHERE r.perfil = ? AND a.status = ? AND a.incorporado_versao IS NULL ORDER BY a.id",
                (perfil, Status.REJEITADO.value),
            ).fetchall()
        return [self._para_apontamento(r) for r in linhas]

    def marcar_execucoes_interrompidas(self) -> None:
        aviso = "Interrompido: o Revisor foi fechado durante a execução. Rode de novo."
        with self._conexao() as con:
            con.execute(
                "UPDATE revisoes SET status = 'ERRO', erro = ? WHERE status IN ('PROCESSANDO', 'PENDENTE')",
                (aviso,),
            )
            con.execute("UPDATE treinos SET status = 'ERRO', erro = ? WHERE status = 'PROCESSANDO'", (aviso,))

    # ---------- histórico de etapas (RF07) ----------
    def registrar_evento(self, revisao_id: int, etapa: str, criado_em: str) -> None:
        with self._conexao() as con:
            con.execute(
                "INSERT INTO eventos_revisao (revisao_id, etapa, criado_em) VALUES (?, ?, ?)",
                (revisao_id, etapa, criado_em),
            )

    def listar_eventos(self, revisao_id: int) -> list[EventoRevisao]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT * FROM eventos_revisao WHERE revisao_id = ? ORDER BY id", (revisao_id,)
            ).fetchall()
        return [EventoRevisao(revisao_id=r["revisao_id"], etapa=r["etapa"], criado_em=r["criado_em"],
                              id=r["id"]) for r in linhas]

    # ---------- treinos ----------
    @staticmethod
    def _para_treino(r: sqlite3.Row) -> Treino:
        dados = dict(r)
        dados["status"] = StatusExecucao(dados["status"])
        dados["completo"] = bool(dados["completo"])
        for campo in ("progresso", "erro", "concluido_em", "avisos"):
            dados[campo] = dados[campo] or ""
        return Treino(**dados)

    def criar_treino(self, treino: Treino) -> int:
        treino.iniciado_em = treino.iniciado_em or _agora()
        valores = asdict(treino)
        with self._conexao() as con:
            cursor = con.execute(
                f"INSERT INTO treinos ({', '.join(_CAMPOS_TREINO)}) "
                f"VALUES ({', '.join('?' for _ in _CAMPOS_TREINO)})",
                tuple(valores[c] for c in _CAMPOS_TREINO),
            )
            treino.id = cursor.lastrowid
        return treino.id

    def salvar_treino(self, treino: Treino) -> None:
        valores = asdict(treino)
        with self._conexao() as con:
            con.execute(
                f"UPDATE treinos SET {', '.join(f'{c} = ?' for c in _CAMPOS_TREINO)} WHERE id = ?",
                tuple(valores[c] for c in _CAMPOS_TREINO) + (treino.id,),
            )

    def obter_treino(self, treino_id: int) -> Treino:
        return self._para_treino(self._um("SELECT * FROM treinos WHERE id = ?", (treino_id,)))

    def ultimo_treino(self, perfil: str) -> Treino | None:
        with self._conexao() as con:
            linha = con.execute(
                "SELECT * FROM treinos WHERE perfil = ? ORDER BY id DESC LIMIT 1", (perfil,)
            ).fetchone()
        return self._para_treino(linha) if linha else None

    def checkpoint(self, perfil: str, projeto: str) -> str | None:
        with self._conexao() as con:
            linha = con.execute(
                "SELECT desde FROM checkpoints WHERE perfil = ? AND projeto = ?", (perfil, projeto)
            ).fetchone()
        return linha["desde"] if linha else None

    def salvar_checkpoint(self, perfil: str, projeto: str, desde: str) -> None:
        with self._conexao() as con:
            con.execute(
                "INSERT INTO checkpoints (perfil, projeto, desde) VALUES (?, ?, ?) "
                "ON CONFLICT (perfil, projeto) DO UPDATE SET desde = excluded.desde",
                (perfil, projeto, desde),
            )

    # ---------- exemplos ----------
    def salvar_exemplo(self, exemplo: Exemplo) -> bool:
        with self._conexao() as con:
            cursor = con.execute(
                "INSERT OR IGNORE INTO exemplos (perfil, projeto, mr_iid, note_id, arquivo, linha, "
                "trecho, comentario, resolvido, autor, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exemplo.perfil, exemplo.projeto, exemplo.mr_iid, exemplo.note_id, exemplo.arquivo,
                 exemplo.linha, exemplo.trecho, exemplo.comentario, int(exemplo.resolvido),
                 exemplo.autor, exemplo.criado_em),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _para_exemplo(r: sqlite3.Row) -> Exemplo:
        return Exemplo(
            perfil=r["perfil"], projeto=r["projeto"], mr_iid=r["mr_iid"], note_id=r["note_id"],
            arquivo=r["arquivo"], linha=r["linha"], trecho=r["trecho"] or "",
            comentario=r["comentario"], resolvido=bool(r["resolvido"]),
            autor=r["autor"] or "", criado_em=r["criado_em"] or "",
        )

    def listar_exemplos(self, perfil: str, limite: int | None = None) -> list[Exemplo]:
        sql = "SELECT * FROM exemplos WHERE perfil = ? ORDER BY resolvido DESC, id DESC"
        parametros: tuple = (perfil,)
        if limite is not None:
            sql += " LIMIT ?"
            parametros += (limite,)
        with self._conexao() as con:
            return [self._para_exemplo(r) for r in con.execute(sql, parametros).fetchall()]

    def listar_exemplos_pendentes(self, perfil: str, escopo: str) -> list[Exemplo]:
        if escopo == GERAL:
            sql = "SELECT * FROM exemplos WHERE perfil = ? AND incorporado_versao IS NULL ORDER BY id"
            parametros: tuple = (perfil,)
        else:
            sql = (
                "SELECT * FROM exemplos WHERE perfil = ? AND projeto = ? "
                "AND incorporado_projeto_versao IS NULL ORDER BY id"
            )
            parametros = (perfil, escopo)
        with self._conexao() as con:
            linhas = con.execute(sql, parametros).fetchall()
        return [self._para_exemplo(r) for r in linhas]

    def obter_exemplos(self, perfil: str, note_ids: list[int]) -> list[Exemplo]:
        if not note_ids:
            return []
        marcadores = ", ".join("?" for _ in note_ids)
        with self._conexao() as con:
            linhas = con.execute(
                f"SELECT * FROM exemplos WHERE perfil = ? AND note_id IN ({marcadores})",
                (perfil, *note_ids),
            ).fetchall()
        por_id = {r["note_id"]: self._para_exemplo(r) for r in linhas}
        return [por_id[n] for n in note_ids if n in por_id]

    def contar_exemplos(self, perfil: str) -> int:
        with self._conexao() as con:
            return con.execute("SELECT COUNT(*) FROM exemplos WHERE perfil = ?", (perfil,)).fetchone()[0]

    def contar_exemplos_pendentes(self, perfil: str) -> int:
        with self._conexao() as con:
            return con.execute(
                "SELECT COUNT(*) FROM exemplos WHERE perfil = ? AND incorporado_versao IS NULL", (perfil,)
            ).fetchone()[0]

    def contar_exemplos_por_projeto(self, perfil: str) -> list[tuple[str, int]]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT projeto, COUNT(*) AS total FROM exemplos WHERE perfil = ? "
                "GROUP BY projeto ORDER BY projeto",
                (perfil,),
            ).fetchall()
        return [(r["projeto"], r["total"]) for r in linhas]

    # ---------- guias ----------
    def salvar_guia(
        self, perfil: str, escopo: str, conteudo: str, note_ids: list[int], apontamento_ids: list[int]
    ) -> int:
        with self._conexao() as con:  # uma transação: versão nova + itens marcados, ou nada
            versao = con.execute(
                "SELECT COALESCE(MAX(versao), 0) + 1 FROM guias WHERE perfil = ? AND escopo = ?",
                (perfil, escopo),
            ).fetchone()[0]
            if escopo == GERAL:
                con.executemany(
                    "UPDATE exemplos SET incorporado_versao = ? WHERE perfil = ? AND note_id = ?",
                    [(versao, perfil, n) for n in note_ids],
                )
                incorporados = con.execute(
                    "SELECT COUNT(*) FROM exemplos WHERE perfil = ? AND incorporado_versao IS NOT NULL",
                    (perfil,),
                ).fetchone()[0]
            else:
                con.executemany(
                    "UPDATE exemplos SET incorporado_projeto_versao = ? "
                    "WHERE perfil = ? AND projeto = ? AND note_id = ?",
                    [(versao, perfil, escopo, n) for n in note_ids],
                )
                incorporados = con.execute(
                    "SELECT COUNT(*) FROM exemplos WHERE perfil = ? AND projeto = ? "
                    "AND incorporado_projeto_versao IS NOT NULL",
                    (perfil, escopo),
                ).fetchone()[0]
            con.executemany(
                "UPDATE apontamentos SET incorporado_versao = ? WHERE id = ?",
                [(versao, i) for i in apontamento_ids],
            )
            con.execute(
                "INSERT INTO guias (perfil, escopo, versao, conteudo, exemplos_usados, criado_em) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (perfil, escopo, versao, conteudo, incorporados, _agora()),
            )
        return versao

    @staticmethod
    def _para_guia(r: sqlite3.Row) -> Guia:
        return Guia(perfil=r["perfil"], escopo=r["escopo"], versao=r["versao"], conteudo=r["conteudo"],
                    exemplos_usados=r["exemplos_usados"], criado_em=r["criado_em"])

    def guia_ativo(self, perfil: str, escopo: str = GERAL) -> Guia | None:
        with self._conexao() as con:
            r = con.execute(
                "SELECT * FROM guias WHERE perfil = ? AND escopo = ? ORDER BY versao DESC LIMIT 1",
                (perfil, escopo),
            ).fetchone()
        return self._para_guia(r) if r else None

    def guia_por_versao(self, perfil: str, versao: int, escopo: str = GERAL) -> Guia | None:
        with self._conexao() as con:
            r = con.execute(
                "SELECT * FROM guias WHERE perfil = ? AND escopo = ? AND versao = ?", (perfil, escopo, versao)
            ).fetchone()
        return self._para_guia(r) if r else None

    def listar_versoes_guia(self, perfil: str, escopo: str = GERAL) -> list[Guia]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT * FROM guias WHERE perfil = ? AND escopo = ? ORDER BY versao DESC", (perfil, escopo)
            ).fetchall()
        return [self._para_guia(r) for r in linhas]

    def listar_escopos_guia(self, perfil: str) -> list[str]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT DISTINCT escopo FROM guias WHERE perfil = ? AND escopo != ? ORDER BY escopo",
                (perfil, GERAL),
            ).fetchall()
        return [r["escopo"] for r in linhas]

    # ---------- mapas técnicos ----------
    def salvar_mapa(self, mapa: MapaProjeto) -> int:
        with self._conexao() as con:
            cursor = con.execute(
                "INSERT INTO mapas (projeto, sha, conteudo, arquivos_lidos, criado_em) VALUES (?, ?, ?, ?, ?)",
                (mapa.projeto, mapa.sha, mapa.conteudo, json.dumps(list(mapa.arquivos_lidos)),
                 mapa.criado_em or _agora()),
            )
            return cursor.lastrowid

    @staticmethod
    def _para_mapa(r: sqlite3.Row) -> MapaProjeto:
        return MapaProjeto(
            id=r["id"], projeto=r["projeto"], sha=r["sha"], conteudo=r["conteudo"],
            arquivos_lidos=tuple(json.loads(r["arquivos_lidos"])), criado_em=r["criado_em"],
        )

    def mapa_ativo(self, projeto: str) -> MapaProjeto | None:
        with self._conexao() as con:
            r = con.execute(
                "SELECT * FROM mapas WHERE projeto = ? ORDER BY id DESC LIMIT 1", (projeto,)
            ).fetchone()
        return self._para_mapa(r) if r else None

    def listar_mapas(self) -> list[MapaProjeto]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT m.* FROM mapas m "
                "JOIN (SELECT projeto, MAX(id) AS id FROM mapas GROUP BY projeto) u "
                "ON u.projeto = m.projeto AND u.id = m.id "
                "ORDER BY m.projeto"
            ).fetchall()
        return [self._para_mapa(r) for r in linhas]

    # ---------- resumo de arquitetura (ADRs) ----------
    def salvar_guia_arquitetura(self, guia: GuiaArquitetura) -> int:
        with self._conexao() as con:
            cursor = con.execute(
                "INSERT INTO guia_arquitetura (projeto_fonte, sha, conteudo, arquivos_lidos, "
                "criado_em) VALUES (?, ?, ?, ?, ?)",
                (guia.projeto_fonte, guia.sha, guia.conteudo,
                 json.dumps(list(guia.arquivos_lidos)), guia.criado_em or _agora()),
            )
            return cursor.lastrowid

    @staticmethod
    def _para_guia_arquitetura(r: sqlite3.Row) -> GuiaArquitetura:
        return GuiaArquitetura(
            id=r["id"], projeto_fonte=r["projeto_fonte"], sha=r["sha"], conteudo=r["conteudo"],
            arquivos_lidos=tuple(json.loads(r["arquivos_lidos"])), criado_em=r["criado_em"],
        )

    def guia_arquitetura_ativo(self) -> GuiaArquitetura | None:
        with self._conexao() as con:
            r = con.execute("SELECT * FROM guia_arquitetura ORDER BY id DESC LIMIT 1").fetchone()
        return self._para_guia_arquitetura(r) if r else None

    # ---------- execução dos agentes especialistas (R6) ----------
    def salvar_execucao_agente(self, execucao: ExecucaoAgente) -> int:
        """Upsert por (revisao_id, agente): grava exatamente os campos recebidos. Quem chama
        preserva `iniciado_em` entre as chamadas de atualização do mesmo agente."""
        execucao.atualizado_em = execucao.atualizado_em or _agora()
        execucao.iniciado_em = execucao.iniciado_em or execucao.atualizado_em
        valores = asdict(execucao)
        with self._conexao() as con:
            con.execute(
                f"INSERT INTO agentes_execucao ({', '.join(_CAMPOS_EXECUCAO_AGENTE)}) "
                f"VALUES ({', '.join('?' for _ in _CAMPOS_EXECUCAO_AGENTE)}) "
                "ON CONFLICT (revisao_id, agente) DO UPDATE SET "
                + ", ".join(f"{c} = excluded.{c}" for c in _CAMPOS_EXECUCAO_AGENTE),
                tuple(valores[c] for c in _CAMPOS_EXECUCAO_AGENTE),
            )
            linha = con.execute(
                "SELECT id FROM agentes_execucao WHERE revisao_id = ? AND agente = ?",
                (execucao.revisao_id, execucao.agente),
            ).fetchone()
        execucao.id = linha["id"]
        return execucao.id

    @staticmethod
    def _para_execucao_agente(r: sqlite3.Row) -> ExecucaoAgente:
        dados = dict(r)
        for campo in ("etapa", "modelo", "iniciado_em", "atualizado_em", "resposta_bruta"):
            dados[campo] = dados[campo] or ""
        for campo in ("tokens_entrada", "tokens_saida", "achados_validos", "achados_descartados"):
            dados[campo] = dados[campo] or 0
        return ExecucaoAgente(**dados)

    def listar_execucoes_agentes(self, revisao_id: int) -> list[ExecucaoAgente]:
        with self._conexao() as con:
            linhas = con.execute(
                "SELECT * FROM agentes_execucao WHERE revisao_id = ? ORDER BY id", (revisao_id,)
            ).fetchall()
        return [self._para_execucao_agente(r) for r in linhas]

    # ---------- descartes do coordenador (R4) ----------
    def salvar_descartes(self, revisao_id: int, descartes: list[Descarte]) -> None:
        if not descartes:
            return
        with self._conexao() as con:
            con.executemany(
                "INSERT INTO descartes_coordenacao (revisao_id, arquivo, linha, severidade, "
                "confianca, comentario, evidencia, motivo, origens, recuperado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (revisao_id, d.arquivo, d.linha, d.severidade.value, d.confianca, d.comentario,
                     d.evidencia, d.motivo, ",".join(d.origens), int(d.recuperado))
                    for d in descartes
                ],
            )

    @staticmethod
    def _para_descarte(r: sqlite3.Row) -> Descarte:
        return Descarte(
            arquivo=r["arquivo"], linha=r["linha"], severidade=Severidade(r["severidade"]),
            confianca=r["confianca"], comentario=r["comentario"], evidencia=r["evidencia"] or "",
            motivo=r["motivo"], origens=tuple(r["origens"].split(",")) if r["origens"] else (),
            recuperado=bool(r["recuperado"]), id=r["id"],
        )

    def listar_descartes(self, revisao_id: int, incluir_recuperados: bool = False) -> list[Descarte]:
        sql = "SELECT * FROM descartes_coordenacao WHERE revisao_id = ?"
        if not incluir_recuperados:
            sql += " AND recuperado = 0"
        sql += " ORDER BY id"
        with self._conexao() as con:
            linhas = con.execute(sql, (revisao_id,)).fetchall()
        return [self._para_descarte(r) for r in linhas]

    def obter_descarte(self, descarte_id: int) -> Descarte:
        return self._para_descarte(
            self._um("SELECT * FROM descartes_coordenacao WHERE id = ?", (descarte_id,))
        )

    def marcar_descarte_recuperado(self, descarte_id: int) -> None:
        with self._conexao() as con:
            con.execute(
                "UPDATE descartes_coordenacao SET recuperado = 1 WHERE id = ?", (descarte_id,)
            )
