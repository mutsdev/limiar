"""Backup do banco — cópia íntegra, poda e idempotência."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from fluxo.persistencia import backup

HOJE = date(2026, 8, 31)


def banco_com_dados(caminho: Path, linhas: int = 5) -> None:
    conn = sqlite3.connect(str(caminho))
    conn.execute("CREATE TABLE evento (id INTEGER PRIMARY KEY, direcao TEXT)")
    conn.executemany(
        "INSERT INTO evento (direcao) VALUES (?)", [("ENTRADA",)] * linhas
    )
    conn.commit()
    conn.close()


class TestFazerBackup:
    def test_copia_e_integra_e_completa(self, tmp_path):
        origem = tmp_path / "fluxo.db"
        banco_com_dados(origem, linhas=7)

        destino = backup.fazer_backup(origem, tmp_path / "backups" / "copia.db")

        conn = sqlite3.connect(str(destino))
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM evento").fetchone()[0] == 7
        conn.close()


class TestPodarAntigos:
    def test_apaga_so_alem_da_retencao(self, tmp_path):
        for dia in ("2026-08-10", "2026-08-20", "2026-08-30"):
            (tmp_path / f"fluxo-{dia}.db").touch()

        apagados = backup.podar_antigos(tmp_path, reter_dias=14, hoje=HOJE)

        assert [p.name for p in apagados] == ["fluxo-2026-08-10.db"]
        assert (tmp_path / "fluxo-2026-08-20.db").exists()
        assert (tmp_path / "fluxo-2026-08-30.db").exists()

    def test_nome_fora_do_padrao_sobrevive(self, tmp_path):
        """Uma cópia manual feita num susto é a que não se pode apagar."""
        estranho = tmp_path / "fluxo-antes-de-mexer.db"
        estranho.touch()
        velho = tmp_path / "fluxo-2026-01-01.db"
        velho.touch()

        backup.podar_antigos(tmp_path, reter_dias=14, hoje=HOJE)

        assert estranho.exists()
        assert not velho.exists()


class TestBackupDiario:
    def test_cria_com_o_nome_do_dia(self, tmp_path):
        origem = tmp_path / "fluxo.db"
        banco_com_dados(origem)
        pasta = tmp_path / "backups"

        criado = backup.backup_diario(origem, pasta, hoje=HOJE)

        assert criado == pasta / "fluxo-2026-08-31.db"
        assert criado.exists()

    def test_segunda_chamada_no_dia_nao_refaz(self, tmp_path):
        origem = tmp_path / "fluxo.db"
        banco_com_dados(origem)
        pasta = tmp_path / "backups"

        primeiro = backup.backup_diario(origem, pasta, hoje=HOJE)
        marca = primeiro.stat().st_mtime_ns
        assert backup.backup_diario(origem, pasta, hoje=HOJE) is None
        assert primeiro.stat().st_mtime_ns == marca

    def test_banco_inexistente_nao_cria_nada(self, tmp_path):
        pasta = tmp_path / "backups"
        assert backup.backup_diario(tmp_path / "nao-existe.db", pasta, hoje=HOJE) is None
        assert not pasta.exists()

    def test_poda_acontece_junto(self, tmp_path):
        origem = tmp_path / "fluxo.db"
        banco_com_dados(origem)
        pasta = tmp_path / "backups"
        pasta.mkdir()
        (pasta / "fluxo-2026-01-01.db").touch()

        backup.backup_diario(origem, pasta, reter_dias=14, hoje=HOJE)

        assert not (pasta / "fluxo-2026-01-01.db").exists()
