#!/usr/bin/env python3
"""Download idempotente de arquivos públicos EOD da B3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path


BASE_URL = "https://www.b3.com.br/pesquisapregao/download"
DATASETS = {
    "SPRD": "Simplified Price Report - Derivatives (BVBG.187.01)",
    "IN": "Instruments File (BVBG.028.02)",
}


class B3FileUnavailable(RuntimeError):
    """A B3 respondeu, mas o arquivo solicitado ainda não existe."""


class B3DownloadError(RuntimeError):
    """Falha transitória ou resposta inválida durante o download."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_name(dataset: str, reference_date: date) -> str:
    return f"{dataset}{reference_date:%y%m%d}.zip"


def validate_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        prefix = path.read_bytes()[:160].decode("utf-8", errors="replace")
        raise ValueError(f"resposta não é ZIP; início do conteúdo: {prefix!r}")
    with zipfile.ZipFile(path) as archive:
        if not archive.namelist():
            raise B3FileUnavailable("arquivo ainda indisponível (ZIP vazio)")
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"membro corrompido no ZIP: {bad_member}")


def zip_member_manifest(path: Path) -> list[dict[str, object]]:
    manifest = []
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            digest = hashlib.sha256()
            with archive.open(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            manifest.append(
                {
                    "name": member.filename,
                    "size_bytes": member.file_size,
                    "sha256": digest.hexdigest(),
                }
            )
    return manifest


def write_metadata(
    path: Path, dataset: str, reference_date: date, url: str, downloaded: bool
) -> None:
    metadata_path = path.with_suffix(path.suffix + ".metadata.json")
    now = datetime.now(timezone.utc).isoformat()
    first_download = now
    last_download = now if downloaded else None
    if metadata_path.exists():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            first_download = previous.get("downloaded_at_utc", now)
            if not downloaded:
                last_download = previous.get("last_downloaded_at_utc", first_download)
        except (OSError, json.JSONDecodeError):
            pass
    payload = {
        "source": "B3 - Pesquisa por Pregão",
        "dataset": dataset,
        "description": DATASETS[dataset],
        "reference_date_requested": reference_date.isoformat(),
        "source_url": url,
        "original_filename": path.name,
        "downloaded_at_utc": first_download,
        "last_downloaded_at_utc": last_download,
        "last_checked_at_utc": now,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "zip_members": zip_member_manifest(path),
        "download_performed": downloaded,
        "status": "validated",
    }
    temporary = metadata_path.with_suffix(metadata_path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, metadata_path)


def download_one(
    dataset: str,
    reference_date: date,
    output_root: Path,
    retries: int,
    timeout: int,
    force: bool,
) -> Path:
    filename = target_name(dataset, reference_date)
    destination = output_root / f"{reference_date:%Y/%m/%d}" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = BASE_URL + "?" + urllib.parse.urlencode({"filelist": filename})

    if destination.exists() and not force:
        validate_zip(destination)
        write_metadata(destination, dataset, reference_date, url, downloaded=False)
        print(f"REUSE {destination} sha256={sha256_file(destination)}")
        return destination

    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "b3-eod-poc/0.1 (+research; public B3 data)",
            "Accept": "application/zip,application/octet-stream,*/*;q=0.1",
        },
    )

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP inesperado: {response.status}")
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            validate_zip(temporary)
            os.replace(temporary, destination)
            write_metadata(destination, dataset, reference_date, url, downloaded=True)
            print(f"OK    {destination} sha256={sha256_file(destination)}")
            return destination
        except B3FileUnavailable:
            temporary.unlink(missing_ok=True)
            raise
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 15))

    raise B3DownloadError(
        f"falha ao baixar {filename} após {retries} tentativa(s): {last_error}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--datasets", nargs="+", choices=sorted(DATASETS), default=["SPRD", "IN"]
    )
    parser.add_argument("--output", type=Path, default=Path("data/raw"))
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures = 0
    for dataset in args.datasets:
        try:
            download_one(
                dataset,
                args.date,
                args.output,
                args.retries,
                args.timeout,
                args.force,
            )
        except Exception as error:
            failures += 1
            print(f"ERROR {dataset}: {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
