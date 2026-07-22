import io
import os
import openpyxl
import pytest


from services.catalog_parser_service import (
    parse_catalog_csv,
    parse_catalog_xlsx,
    parse_catalog_bytes,
)

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "ARVENA_Upload_Ready_Catalog.csv"
)


def test_real_arvena_csv_golden_fixture():
    assert os.path.exists(FIXTURE_PATH), f"Fixture not found at {FIXTURE_PATH}"
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()

    result = parse_catalog_csv(content)
    stats = result.stats
    records = result.records

    assert stats["total_rows_seen"] == 14
    assert stats["accepted_records"] == 14
    assert stats["rejected_rows"] == 0
    assert stats["product_count"] == 11
    assert stats["bundle_count"] == 3
    assert len(records) == 14


def test_exact_arvena_price_truth():
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()

    result = parse_catalog_csv(content)
    records_by_name = {r["name"]: r for r in result.records}

    ergo_one = records_by_name["Arvena Ergo One"]
    assert ergo_one["price"] == 6900.0
    assert ergo_one["currency"] == "EGP"
    assert ergo_one["sku"] == "AR-CHR-001"

    ergo_pro = records_by_name["Arvena Ergo Pro"]
    assert ergo_pro["price"] == 10900.0

    focus_120 = records_by_name["FocusDesk 120"]
    assert focus_120["price"] == 8500.0


def test_bundle_distinction():
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()

    result = parse_catalog_csv(content)
    bundles = [r for r in result.records if r["record_type"] == "bundle"]
    assert len(bundles) == 3

    home_office_start = next(
        b for b in bundles if "Home Office Start" in b["name"]
    )
    assert home_office_start["record_type"] == "bundle"
    assert home_office_start["components_text"] == "Ergo One + FocusDesk 120 + CleanCable Kit"
    assert "included_skus" not in home_office_start


def test_quantity_discount_parsing():
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()

    result = parse_catalog_csv(content)
    ergo_one = next(r for r in result.records if r["name"] == "Arvena Ergo One")

    discounts = ergo_one["quantity_discounts"]
    assert len(discounts) == 3

    t1 = next(d for d in discounts if d["min_qty"] == 3)
    assert t1["max_qty"] == 4
    assert t1["discount_pct"] == 5.0

    t2 = next(d for d in discounts if d["min_qty"] == 5)
    assert t2["max_qty"] == 9
    assert t2["discount_pct"] == 8.0

    t3 = next(d for d in discounts if d["min_qty"] == 10)
    assert t3["max_qty"] is None
    assert t3["discount_pct"] == 12.0


def test_arabic_header_aliases():
    csv_data = (
        "نوع_السجل,كود,الاسم,السعر,العملة,المخزون\n"
        "منتج,P001,كرسي فاخر,1500,جنيه,10\n"
    )
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 1
    rec = result.records[0]
    assert rec["record_type"] == "product"
    assert rec["sku"] == "P001"
    assert rec["name"] == "كرسي فاخر"
    assert rec["price"] == 1500.0
    assert rec["currency"] == "EGP"
    assert rec["stock"] == 10


def test_english_header_aliases():
    csv_data = (
        "record_type,sku,name,price,currency,stock,installation_fee\n"
        "product,ENG-01,Executive Desk,12000,USD,5,150\n"
    )
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 1
    rec = result.records[0]
    assert rec["record_type"] == "product"
    assert rec["sku"] == "ENG-01"
    assert rec["name"] == "Executive Desk"
    assert rec["price"] == 12000.0
    assert rec["currency"] == "USD"
    assert rec["stock"] == 5
    assert rec["installation_fee"] == 150.0


def test_utf8_bom_csv():
    csv_str = (
        "نوع_السجل,كود,الاسم,السعر\n"
        "product,BOM-1,BOM Product,250\n"
    )
    bom_bytes = "\ufeff".encode("utf-8") + csv_str.encode("utf-8")
    result = parse_catalog_csv(bom_bytes)
    assert result.stats["accepted_records"] == 1
    rec = result.records[0]
    assert rec["name"] == "BOM Product"
    assert rec["price"] == 250.0


def test_xlsx_parsing():
    wb = openpyxl.Workbook()


    # Catalog Sheet
    ws1 = wb.active
    ws1.title = "Catalog"
    ws1.append(["record_type", "sku", "name", "price", "currency"])
    ws1.append(["product", "XLS-1", "XLSX Chair", 3500, "EGP"])

    # Unrelated Sheet
    ws2 = wb.create_sheet("Random Notes")
    ws2.append(["Date", "Auditor", "Comment"])
    ws2.append(["2026-07-04", "Admin", "Checked inventory"])

    buf = io.BytesIO()
    wb.save(buf)
    content = buf.getvalue()

    result = parse_catalog_xlsx(content)
    assert result.stats["accepted_records"] == 1
    rec = result.records[0]
    assert rec["sku"] == "XLS-1"
    assert rec["name"] == "XLSX Chair"
    assert rec["price"] == 3500.0

    # Unrelated sheet should trigger warning diagnostic
    warnings = [i for i in result.issues if i["code"] == "NO_CATALOG_HEADER"]
    assert len(warnings) == 1
    assert warnings[0]["sheet"] == "Random Notes"


def test_malformed_required_data():
    csv_data = (
        "record_type,sku,name,price\n"
        "product,P01,,1000\n"  # missing name
        "product,P02,Valid Product,2000\n"
    )
    result = parse_catalog_csv(csv_data)
    assert result.stats["total_rows_seen"] == 2
    assert result.stats["accepted_records"] == 1
    assert result.stats["rejected_rows"] == 1

    missing_name_issues = [i for i in result.issues if i["code"] == "MISSING_NAME"]
    assert len(missing_name_issues) == 1
    assert missing_name_issues[0]["row"] == 2


def test_invalid_numeric_values():
    csv_data = (
        "record_type,name,price,stock,خصم_3_الى_4\n"
        "product,Bad Numbers Product,abc,-2,150\n"
    )
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 1
    rec = result.records[0]
    assert rec["price"] is None
    assert rec["stock"] is None
    assert rec["quantity_discounts"] == []

    codes = [i["code"] for i in result.issues]
    assert "INVALID_PRICE" in codes
    assert "INVALID_STOCK" in codes
    assert "INVALID_DISCOUNT" in codes


def test_unknown_columns():
    csv_data = (
        "record_type,name,price,supplier_id,warehouse_loc\n"
        "product,Test Unknown,500,SUP-99,Zone-A\n"
    )
    result = parse_catalog_csv(csv_data)
    rec = result.records[0]
    assert rec["extra_fields"]["supplier_id"] == "SUP-99"
    assert rec["extra_fields"]["warehouse_loc"] == "Zone-A"


def test_purity_boundary():
    # Pure function: run without DB session, network, or external context
    csv_data = "name,price\nPure Item,100\n"
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 1
    assert result.records[0]["name"] == "Pure Item"


def test_determinism():
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()

    r1 = parse_catalog_csv(content)
    r2 = parse_catalog_csv(content)

    assert r1.to_dict() == r2.to_dict()


def test_missing_values_are_not_invented():
    csv_data = (
        "name\n"
        "Bare Product\n"
    )
    result = parse_catalog_csv(csv_data)
    rec = result.records[0]

    assert rec["price"] is None
    assert rec["currency"] is None
    assert rec["stock"] is None
    assert rec["sku"] is None
    assert "installment_available" not in rec


def test_unsupported_pipe_delimiter_safety():
    csv_data = "name|price|currency\nChair|6900|EGP\n"
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 0
    assert result.stats["total_rows_seen"] == 0
    assert len(result.records) == 0
    errs = [i for i in result.issues if i["code"] == "UNSUPPORTED_DELIMITER"]
    assert len(errs) == 1


def test_semicolon_and_tab_delimiter_support():
    semi_data = "name;price;currency\nSemi Chair;4000;EGP\n"
    res_semi = parse_catalog_csv(semi_data)
    assert res_semi.stats["accepted_records"] == 1
    assert res_semi.records[0]["name"] == "Semi Chair"

    tab_data = "name\tprice\tcurrency\nTab Desk\t8000\tUSD\n"
    res_tab = parse_catalog_csv(tab_data)
    assert res_tab.stats["accepted_records"] == 1
    assert res_tab.records[0]["name"] == "Tab Desk"


def test_cp1256_binary_garbage_safety():
    # Random binary bytes that fail UTF-8 decoding
    garbage_bytes = bytes(range(128, 255))
    result = parse_catalog_csv(garbage_bytes)
    assert result.stats["accepted_records"] == 0
    assert result.stats["total_rows_seen"] == 0
    assert len(result.records) == 0


def test_random_non_catalog_text_safety():
    csv_data = "Date,Auditor,Comment\n2026-07-04,Admin,Checked\n"
    result = parse_catalog_csv(csv_data)
    assert result.stats["accepted_records"] == 0
    assert result.stats["total_rows_seen"] == 0
    warnings = [i for i in result.issues if i["code"] == "NO_CATALOG_HEADER"]
    assert len(warnings) == 1

