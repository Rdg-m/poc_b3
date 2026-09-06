"""Carga validada do staging BVBG.187.01 em Dolt via protocolo MySQL."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

from b3_parse_bvbg187 import BATCH_COLUMNS, PRICE_COLUMNS


@dataclass(frozen=True)
class DoltConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    branch: str
    ssl_mode: str
    ssl_ca: str | None
    connect_timeout: int
    commit_author: str | None

    @classmethod
    def from_environment(cls) -> "DoltConfig":
        required = ["DOLT_HOST", "DOLT_DATABASE", "DOLT_USER"]
        missing = [name for name in required if not os.environ.get(name)]
        if "DOLT_PASSWORD" not in os.environ:
            missing.append("DOLT_PASSWORD")
        if missing:
            raise ValueError("variáveis obrigatórias ausentes: " + ", ".join(missing))
        ssl_mode = os.environ.get("DOLT_SSL_MODE", "REQUIRED").upper()
        allowed_ssl_modes = {"DISABLED", "REQUIRED", "VERIFY_IDENTITY"}
        if ssl_mode not in allowed_ssl_modes:
            raise ValueError(
                f"DOLT_SSL_MODE inválido: {ssl_mode!r}; use {sorted(allowed_ssl_modes)}"
            )
        return cls(
            host=os.environ["DOLT_HOST"],
            port=int(os.environ.get("DOLT_PORT", "3306")),
            database=os.environ["DOLT_DATABASE"],
            user=os.environ["DOLT_USER"],
            password=os.environ["DOLT_PASSWORD"],
            branch=os.environ.get("DOLT_BRANCH", "main"),
            ssl_mode=ssl_mode,
            ssl_ca=os.environ.get("DOLT_SSL_CA") or None,
            connect_timeout=int(os.environ.get("DOLT_CONNECT_TIMEOUT", "15")),
            commit_author=os.environ.get("DOLT_COMMIT_AUTHOR") or None,
        )


def connect(config: DoltConfig):
    try:
        import pymysql
    except ImportError as error:
        raise RuntimeError("dependência ausente; execute: pip install -r requirements.txt") from error

    ssl = None
    if config.ssl_mode != "DISABLED":
        ssl = {"check_hostname": False}
        if config.ssl_ca:
            ssl["ca"] = config.ssl_ca
        if config.ssl_mode == "VERIFY_IDENTITY":
            ssl["check_hostname"] = True
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=config.connect_timeout,
        read_timeout=120,
        write_timeout=120,
        ssl=ssl,
    )


def read_tsv(path: Path) -> list[dict[str, str | None]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [
            {key: None if value == r"\N" else value for key, value in row.items()}
            for row in csv.DictReader(stream, delimiter="\t")
        ]


def execute_ddl(cursor, ddl_path: Path) -> None:
    source = ddl_path.read_text(encoding="utf-8")
    statements = []
    current = []
    for line in source.splitlines():
        if line.lstrip().startswith("--"):
            continue
        current.append(line)
    for statement in "\n".join(current).split(";"):
        if statement.strip():
            statements.append(statement.strip())
    for statement in statements:
        cursor.execute(statement)


def dolt_status(cursor) -> list[dict]:
    cursor.execute("SELECT table_name, staged, status FROM dolt_status")
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def assert_dolt_and_branch(cursor, expected_branch: str) -> str:
    try:
        cursor.execute("SELECT active_branch()")
        active = cursor.fetchone()[0]
    except Exception as error:
        raise RuntimeError("o destino não respondeu como uma instância Dolt") from error
    if active != expected_branch:
        raise RuntimeError(f"branch Dolt ativa é {active!r}; esperado {expected_branch!r}")
    return active


def placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def load(
    connection,
    staging_dir: Path,
    ddl_path: Path,
    min_rows: int,
    min_prior_ratio: float,
    expected_branch: str,
    commit_author: str | None,
) -> dict[str, object]:
    batches = read_tsv(staging_dir / "b3_ingestion_batch.tsv")
    prices = read_tsv(staging_dir / "stg_b3_derivatives_price.tsv")
    if len(batches) != 1:
        raise ValueError(f"esperado exatamente um lote; recebido: {len(batches)}")
    batch = batches[0]
    reference_date = batch["reference_date"]
    batch_id = batch["batch_id"]
    if len(prices) < min_rows:
        raise ValueError(f"guardrail: apenas {len(prices)} linhas; mínimo configurado: {min_rows}")
    if int(batch["row_count"] or -1) != len(prices):
        raise ValueError("row_count do manifesto diverge do TSV")
    if {row["trade_date"] for row in prices} != {reference_date}:
        raise ValueError("TSV contém data diferente da data do lote")
    keys = {(row["trade_date"], row["instrument_id"]) for row in prices}
    if len(keys) != len(prices):
        raise ValueError("TSV contém chaves de negócio duplicadas")

    try:
        with connection.cursor() as cursor:
            active_branch = assert_dolt_and_branch(cursor, expected_branch)
            dirty_before = dolt_status(cursor)
            if dirty_before:
                raise RuntimeError(
                    "guardrail: working set Dolt já contém mudanças não commitadas: "
                    + repr(dirty_before)
                )

            execute_ddl(cursor, ddl_path)
            cursor.execute(
                "SELECT trade_date, COUNT(*) FROM stg_b3_derivatives_price "
                "WHERE trade_date < %s GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1",
                (reference_date,),
            )
            previous = cursor.fetchone()
            if previous and previous[1] >= min_rows:
                ratio = len(prices) / previous[1]
                if ratio < min_prior_ratio:
                    raise ValueError(
                        f"guardrail: volume atual é {ratio:.2%} do pregão anterior "
                        f"({len(prices)} contra {previous[1]})"
                    )

            batch_columns = ", ".join(f"`{name}`" for name in BATCH_COLUMNS)
            cursor.execute(
                f"INSERT IGNORE INTO b3_ingestion_batch ({batch_columns}) "
                f"VALUES ({placeholders(len(BATCH_COLUMNS))})",
                tuple(batch[name] for name in BATCH_COLUMNS),
            )

            price_columns = ", ".join(f"`{name}`" for name in PRICE_COLUMNS)
            updates = ", ".join(
                f"`{name}` = VALUES(`{name}`)"
                for name in PRICE_COLUMNS
                if name not in {"trade_date", "instrument_id"}
            )
            statement = (
                f"INSERT INTO stg_b3_derivatives_price ({price_columns}) "
                f"VALUES ({placeholders(len(PRICE_COLUMNS))}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
            for offset in range(0, len(prices), 500):
                chunk = prices[offset : offset + 500]
                cursor.executemany(
                    statement,
                    [tuple(row[name] for name in PRICE_COLUMNS) for row in chunk],
                )

            cursor.execute(
                "DELETE FROM stg_b3_derivatives_price "
                "WHERE trade_date = %s AND batch_id <> %s",
                (reference_date, batch_id),
            )
            deleted_stale_rows = cursor.rowcount

            cursor.execute(
                "SELECT COUNT(*), COUNT(DISTINCT instrument_id), "
                "SUM(batch_id <> %s) FROM stg_b3_derivatives_price WHERE trade_date = %s",
                (batch_id, reference_date),
            )
            total, unique_instruments, wrong_batch = cursor.fetchone()
            if total != len(prices) or unique_instruments != total or int(wrong_batch or 0):
                raise RuntimeError(
                    "validação pós-carga falhou: "
                    f"total={total}, únicos={unique_instruments}, lote_divergente={wrong_batch}"
                )

            cursor.execute("CALL DOLT_VERIFY_CONSTRAINTS()")
            constraint_row = cursor.fetchone()
            violations = int(constraint_row[0]) if constraint_row else 0
            while cursor.nextset():
                pass
            if violations:
                raise RuntimeError(f"guardrail: Dolt encontrou {violations} violação(ões)")
            status_before_commit = dolt_status(cursor)
            message = f"B3 BVBG.187.01 EOD {reference_date} batch {batch_id[:12]}"
            arguments = ["-Am", message, "--skip-empty"]
            if commit_author:
                arguments.extend(["--author", commit_author])
            cursor.execute(
                f"CALL DOLT_COMMIT({placeholders(len(arguments))})",
                tuple(arguments),
            )
            commit_row = cursor.fetchone()
            commit_hash = commit_row[0] if commit_row and commit_row[0] else None
            while cursor.nextset():
                pass
            connection.commit()
            clean_after = dolt_status(cursor)
            if clean_after:
                raise RuntimeError("guardrail: working set permaneceu sujo após o commit")
            return {
                "branch": active_branch,
                "reference_date": reference_date,
                "batch_id": batch_id,
                "rows": total,
                "deleted_stale_rows": deleted_stale_rows,
                "changes_before_commit": status_before_commit,
                "commit_hash": commit_hash,
                "outcome": "committed" if commit_hash else "no_changes",
            }
    except Exception:
        connection.rollback()
        raise
