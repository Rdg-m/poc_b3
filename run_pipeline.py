#!/usr/bin/env python3
"""Pipeline único: último pregão B3 -> parsing -> staging -> commit Dolt."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from b3_download import B3FileUnavailable, download_one
from b3_parse_bvbg187 import parse
from dolt_loader import DoltConfig, connect, load


LOG = logging.getLogger("b3_pipeline")
PROJECT_ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("outra execução do pipeline já está ativa") from error
        stream.write(str(os.getpid()))
        stream.flush()
        yield


def sao_paulo_today() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def discover_latest(
    start_date: date,
    lookback_days: int,
    raw_root: Path,
    retries: int,
    timeout: int,
    refresh: bool,
) -> tuple[date, Path]:
    if lookback_days < 1 or lookback_days > 31:
        raise ValueError("lookback-days deve estar entre 1 e 31")
    for days_back in range(lookback_days):
        candidate = start_date - timedelta(days=days_back)
        LOG.info("Consultando disponibilidade do SPRD para %s", candidate)
        try:
            path = download_one(
                "SPRD", candidate, raw_root, retries, timeout, force=refresh
            )
            return candidate, path
        except B3FileUnavailable:
            LOG.info("SPRD indisponível para %s", candidate)
    raise RuntimeError(
        f"nenhum arquivo SPRD encontrado entre {start_date} e "
        f"{start_date - timedelta(days=lookback_days - 1)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="data explícita para backfill")
    parser.add_argument("--lookback-days", type=int, default=10)
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--reuse-download",
        action="store_true",
        help="não consulta novamente a B3 quando já existe cópia local válida",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="baixa, transforma e valida, mas não conecta ao Dolt",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv(args.env_file)
    raw_root = args.data_root / "raw"
    staging_root = args.data_root / "staging"
    lock_path = args.data_root / ".pipeline.lock"
    start_date = args.date or sao_paulo_today()
    try:
        with exclusive_lock(lock_path):
            reference_date, raw_path = discover_latest(
                start_date=start_date,
                lookback_days=1 if args.date else args.lookback_days,
                raw_root=raw_root,
                retries=args.retries,
                timeout=args.timeout,
                refresh=not args.reuse_download,
            )
            staging_dir = staging_root / reference_date.isoformat()
            manifest = parse(raw_path, staging_dir)
            parsed_date = date.fromisoformat(manifest["batch"]["reference_date"])
            if parsed_date != reference_date:
                raise RuntimeError(
                    f"guardrail: solicitado {reference_date}, XML contém {parsed_date}"
                )
            if parsed_date > sao_paulo_today():
                raise RuntimeError("guardrail: XML contém data futura")

            min_rows = int(os.environ.get("B3_MIN_ROWS", "1000"))
            min_prior_ratio = float(os.environ.get("B3_MIN_PRIOR_RATIO", "0.50"))
            if manifest["batch"]["row_count"] < min_rows:
                raise RuntimeError(
                    f"guardrail: {manifest['batch']['row_count']} linhas, mínimo {min_rows}"
                )

            if args.dry_run:
                result = {
                    "outcome": "dry_run_validated",
                    "reference_date": reference_date.isoformat(),
                    "rows": manifest["batch"]["row_count"],
                    "batch_id": manifest["batch"]["batch_id"],
                    "raw_file": str(raw_path),
                    "staging_dir": str(staging_dir),
                }
            else:
                config = DoltConfig.from_environment()
                connection = connect(config)
                try:
                    result = load(
                        connection=connection,
                        staging_dir=staging_dir,
                        ddl_path=PROJECT_ROOT / "sql/001_staging_bvbg187.sql",
                        min_rows=min_rows,
                        min_prior_ratio=min_prior_ratio,
                        expected_branch=config.branch,
                        commit_author=config.commit_author,
                    )
                finally:
                    connection.close()

            summary_path = staging_dir / "pipeline_result.json"
            summary_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except Exception as error:
        LOG.exception("Pipeline interrompido com segurança: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

