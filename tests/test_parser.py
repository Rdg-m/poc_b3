from __future__ import annotations

import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b3_parse_bvbg187 import parse  # noqa: E402


XML = b'''<?xml version="1.0" encoding="utf-8"?>
<Document xmlns="urn:bvmf.052.01.xsd">
  <BizFileHdr><Xchg><BizGrpDesc><BizGrpDtls>
    <BizGrpIdr>TEST-GROUP</BizGrpIdr><BizGrpTp>BVBG.187.01</BizGrpTp>
    <CreDtAndTm>2026-09-04T20:30:13</CreDtAndTm>
  </BizGrpDtls></BizGrpDesc><BizGrp>
    <Document xmlns="urn:bvmf.217.01.xsd"><PricRpt>
      <TradDt><Dt>2026-09-04</Dt></TradDt>
      <SctyId><TckrSymb>CCMU27P007000</TckrSymb></SctyId>
      <FinInstrmId><OthrId><Id>400000106823</Id><Tp><Prtry>8</Prtry></Tp></OthrId>
        <PlcOfListg><MktIdrCd>BVMF</MktIdrCd></PlcOfListg></FinInstrmId>
      <FinInstrmAttrbts><OpnIntrst>10</OpnIntrst>
        <LastPric Ccy="BRL">1.25</LastPric><RglrTxsQty>2</RglrTxsQty>
      </FinInstrmAttrbts>
    </PricRpt></Document>
  </BizGrp></Xchg></BizFileHdr>
</Document>'''


class ParserTest(unittest.TestCase):
    def test_nested_zip_and_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inner_bytes = io.BytesIO()
            with zipfile.ZipFile(inner_bytes, "w", zipfile.ZIP_DEFLATED) as inner:
                inner.writestr("BVBG.187.01_test.xml", XML)
            source = root / "SPRD260904.zip"
            with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as outer:
                outer.writestr("SPRD260904.zip", inner_bytes.getvalue())
            result = parse(source, root / "output")
            self.assertEqual(result["batch"]["row_count"], 1)
            prices = (root / "output/stg_b3_derivatives_price.tsv").read_text()
            self.assertIn("CCMU27P007000", prices)
            self.assertIn("\t1.25\tBRL\t", prices)


if __name__ == "__main__":
    unittest.main()

