#!/usr/bin/env python3
"""Converte um pacote SPRD / BVBG.187.01 da B3 em TSVs para staging Dolt."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


PARSER_VERSION = "0.3.0"
NULL = r"\N"

PRICE_COLUMNS = [
    "trade_date", "instrument_id", "ticker_symbol", "instrument_id_type",
    "market_identifier_code", "open_interest", "first_price",
    "first_price_currency", "minimum_price", "minimum_price_currency",
    "maximum_price", "maximum_price_currency", "average_price",
    "average_price_currency", "last_price", "last_price_currency",
    "regular_transactions_qty", "adjusted_quote", "adjusted_quote_currency",
    "adjusted_quote_status", "adjusted_quote_tax", "adjusted_quote_tax_ccy",
    "previous_adjusted_quote", "previous_adj_quote_ccy",
    "previous_adj_quote_status", "previous_adj_quote_tax",
    "previous_adj_quote_tax_ccy", "batch_id", "row_sha256",
]

BATCH_COLUMNS = [
    "batch_id", "dataset", "business_file_type", "business_group_id",
    "reference_date", "xml_created_at", "source_outer_filename",
    "source_inner_filename", "source_xml_filename", "source_outer_sha256",
    "source_xml_sha256", "snapshot_count", "row_count", "parser_version",
    "ingested_at_utc",
]

FIELD_MAP = {
    "OpnIntrst": "open_interest",
    "FrstPric": "first_price",
    "MinPric": "minimum_price",
    "MaxPric": "maximum_price",
    "TradAvrgPric": "average_price",
    "LastPric": "last_price",
    "RglrTxsQty": "regular_transactions_qty",
    "AdjstdQt": "adjusted_quote",
    "AdjstdQtStin": "adjusted_quote_status",
    "AdjstdQtTax": "adjusted_quote_tax",
    "PrvsAdjstdQt": "previous_adjusted_quote",
    "PrvsAdjstdQtStin": "previous_adj_quote_status",
    "PrvsAdjstdQtTax": "previous_adj_quote_tax",
}

CURRENCY_MAP = {
    "FrstPric": "first_price_currency",
    "MinPric": "minimum_price_currency",
    "MaxPric": "maximum_price_currency",
    "TradAvrgPric": "average_price_currency",
    "LastPric": "last_price_currency",
    "AdjstdQt": "adjusted_quote_currency",
    "AdjstdQtTax": "adjusted_quote_tax_ccy",
    "PrvsAdjstdQt": "previous_adj_quote_ccy",
    "PrvsAdjstdQtTax": "previous_adj_quote_tax_ccy",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def child(element, *path):
    current = element
    for expected in path:
        current = next((item for item in current if local_name(item.tag) == expected), None)
        if current is None:
            return None
    return current


def value(element, *path):
    found = child(element, *path)
    if found is None or found.text is None or not found.text.strip():
        return None
    return found.text.strip()


def tsv_value(item) -> str:
    if item is None or item == "":
        return NULL
    return str(item).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def canonical_row_hash(row: dict[str, object]) -> str:
    business_columns = PRICE_COLUMNS[:27]
    payload = json.dumps(
        [row.get(column) for column in business_columns],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def open_selected_snapshot(outer_path: Path):
    outer = zipfile.ZipFile(outer_path)
    inner_members = [item for item in outer.infolist() if item.filename.lower().endswith(".zip")]
    if not inner_members:
        outer.close()
        raise ValueError("ZIP externo não contém um ZIP interno")
    inner_info = sorted(inner_members, key=lambda item: (item.date_time, item.filename))[-1]
    inner_bytes = outer.read(inner_info)
    inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
    xml_members = [item for item in inner.infolist() if item.filename.lower().endswith(".xml")]
    if not xml_members:
        inner.close()
        outer.close()
        raise ValueError("ZIP interno não contém snapshots XML")
    candidates = []
    for item in xml_members:
        header = scan_header(inner, item)
        candidates.append(
            (header["xml_created_at"] or "", item.date_time, item.filename, item, header)
        )
    _, _, _, selected, selected_header = sorted(candidates)[-1]
    return outer, inner, inner_info, xml_members, selected, selected_header


def scan_header(inner: zipfile.ZipFile, selected: zipfile.ZipInfo) -> dict[str, str | None]:
    header = {"business_file_type": None, "business_group_id": None, "xml_created_at": None}
    with inner.open(selected) as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            name = local_name(element.tag)
            text = (element.text or "").strip() or None
            if name == "BizGrpTp" and header["business_file_type"] is None:
                header["business_file_type"] = text
            elif name == "BizGrpIdr" and header["business_group_id"] is None:
                header["business_group_id"] = text
            elif name == "CreDtAndTm" and header["xml_created_at"] is None:
                header["xml_created_at"] = text
            element.clear()
            if all(header.values()):
                break
    if header["business_file_type"] != "BVBG.187.01":
        raise ValueError(f"tipo de arquivo inesperado: {header['business_file_type']!r}")
    return header


def parse_report(report, batch_id: str) -> dict[str, object]:
    row: dict[str, object] = {column: None for column in PRICE_COLUMNS}
    row.update(
        {
            "trade_date": value(report, "TradDt", "Dt"),
            "ticker_symbol": value(report, "SctyId", "TckrSymb"),
            "instrument_id": value(report, "FinInstrmId", "OthrId", "Id"),
            "instrument_id_type": value(report, "FinInstrmId", "OthrId", "Tp", "Prtry"),
            "market_identifier_code": value(report, "FinInstrmId", "PlcOfListg", "MktIdrCd"),
            "batch_id": batch_id,
        }
    )
    attributes = child(report, "FinInstrmAttrbts")
    if attributes is not None:
        for element in attributes:
            source_name = local_name(element.tag)
            target_name = FIELD_MAP.get(source_name)
            if target_name:
                row[target_name] = (element.text or "").strip() or None
            currency_name = CURRENCY_MAP.get(source_name)
            if currency_name:
                row[currency_name] = element.attrib.get("Ccy")
    required = ("trade_date", "instrument_id", "ticker_symbol")
    missing = [name for name in required if not row[name]]
    if missing:
        raise ValueError(f"PricRpt sem campo(s) obrigatório(s): {', '.join(missing)}")
    row["row_sha256"] = canonical_row_hash(row)
    return row


def parse(outer_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outer, inner, inner_info, xml_members, selected, header = open_selected_snapshot(outer_path)
    try:
        with inner.open(selected) as xml_stream:
            xml_sha256 = sha256_stream(xml_stream)
        batch_id = xml_sha256
        ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        prices_path = output_dir / "stg_b3_derivatives_price.tsv"
        temporary_prices = prices_path.with_suffix(prices_path.suffix + ".part")
        row_count = 0
        trade_dates: set[str] = set()
        keys: set[tuple[str, str]] = set()
        with temporary_prices.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(
                target,
                fieldnames=PRICE_COLUMNS,
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            with inner.open(selected) as xml_stream:
                for _, element in ElementTree.iterparse(xml_stream, events=("end",)):
                    if local_name(element.tag) != "PricRpt":
                        continue
                    row = parse_report(element, batch_id)
                    key = (str(row["trade_date"]), str(row["instrument_id"]))
                    if key in keys:
                        raise ValueError(f"chave duplicada no snapshot: {key}")
                    keys.add(key)
                    trade_dates.add(key[0])
                    writer.writerow({name: tsv_value(row[name]) for name in PRICE_COLUMNS})
                    row_count += 1
                    element.clear()
        if len(trade_dates) != 1:
            raise ValueError(f"snapshot contém datas inesperadas: {sorted(trade_dates)}")
        reference_date = next(iter(trade_dates))
        os.replace(temporary_prices, prices_path)

        batch = {
            "batch_id": batch_id,
            "dataset": "SPRD",
            "business_file_type": header["business_file_type"],
            "business_group_id": header["business_group_id"],
            "reference_date": reference_date,
            "xml_created_at": (header["xml_created_at"] or "").replace("T", " "),
            "source_outer_filename": outer_path.name,
            "source_inner_filename": inner_info.filename,
            "source_xml_filename": selected.filename,
            "source_outer_sha256": sha256_path(outer_path),
            "source_xml_sha256": xml_sha256,
            "snapshot_count": len(xml_members),
            "row_count": row_count,
            "parser_version": PARSER_VERSION,
            "ingested_at_utc": ingested_at,
        }
        batch_path = output_dir / "b3_ingestion_batch.tsv"
        temporary_batch = batch_path.with_suffix(batch_path.suffix + ".part")
        with temporary_batch.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=BATCH_COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow({name: tsv_value(batch[name]) for name in BATCH_COLUMNS})
        os.replace(temporary_batch, batch_path)

        manifest = {
            "parser_version": PARSER_VERSION,
            "batch": batch,
            "outputs": {
                "batch_tsv": str(batch_path),
                "prices_tsv": str(prices_path),
            },
            "selection_rule": "latest embedded CreDtAndTm, ZIP timestamp, then filename",
            "available_snapshots": [item.filename for item in xml_members],
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest
    finally:
        inner.close()
        outer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="ZIP externo SPRDAAMMDD.zip")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(parse(args.input, args.output), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"input": str(args.input), "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
