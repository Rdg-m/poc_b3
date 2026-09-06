#!/usr/bin/env python3
"""Inspeciona o empacotamento e o XML de arquivos públicos da B3."""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_inner_zip(outer_path: Path) -> tuple[str, bytes]:
    with zipfile.ZipFile(outer_path) as outer:
        candidates = [name for name in outer.namelist() if name.lower().endswith(".zip")]
        if not candidates:
            raise ValueError("ZIP externo não contém o ZIP esperado")
        name = candidates[-1]
        return name, outer.read(name)


def inspect_xml(inner: zipfile.ZipFile, member: zipfile.ZipInfo, count_records: bool) -> dict:
    result: dict[str, object] = {
        "name": member.filename,
        "size_bytes": member.file_size,
        "compressed_bytes": member.compress_size,
        "zip_timestamp": "%04d-%02d-%02dT%02d:%02d:%02d" % member.date_time,
    }
    total = 0
    tickers: list[str] = []
    trade_dates: set[str] = set()
    business_type = None
    created_at = None

    with inner.open(member) as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            name = local_name(element.tag)
            text = (element.text or "").strip()
            if name == "BizGrpTp" and business_type is None:
                business_type = text
            elif name == "CreDtAndTm" and created_at is None:
                created_at = text
            elif name == "TckrSymb" and len(tickers) < 5:
                tickers.append(text)
            elif name == "Dt" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                trade_dates.add(text)
            elif name == "PricRpt":
                total += 1
            element.clear()
            if not count_records and business_type and created_at and trade_dates and tickers:
                break

    result.update(
        {
            "business_file_type": business_type,
            "created_at": created_at,
            "trade_dates_seen": sorted(trade_dates),
            "sample_tickers": tickers,
            "price_report_count": total if count_records else None,
        }
    )
    return result


def inspect(path: Path, count_records: bool) -> dict:
    inner_name, inner_bytes = read_inner_zip(path)
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner:
        members = [
            info for info in inner.infolist() if info.filename.lower().endswith(".xml")
        ]
        if not members:
            raise ValueError("ZIP interno não contém XML")
        candidates = []
        for member in members:
            header = inspect_xml(inner, member, count_records=False)
            candidates.append(
                (header.get("created_at") or "", member.date_time, member.filename, member)
            )
        selected = sorted(candidates)[-1][-1]
        return {
            "outer_file": str(path),
            "outer_size_bytes": path.stat().st_size,
            "inner_zip": inner_name,
            "xml_snapshot_count": len(members),
            "selected_snapshot_rule": "latest embedded CreDtAndTm, ZIP timestamp, then filename",
            "selected_snapshot": inspect_xml(inner, selected, count_records),
            "all_xml_members": [item.filename for item in sorted(members, key=lambda x: x.filename)],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--count-records", action="store_true")
    args = parser.parse_args()
    failures = 0
    for path in args.files:
        try:
            print(json.dumps(inspect(path, args.count_records), ensure_ascii=False, indent=2))
        except Exception as error:
            failures += 1
            print(json.dumps({"file": str(path), "error": str(error)}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
