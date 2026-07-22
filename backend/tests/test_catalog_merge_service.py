"""
Comprehensive tests for CatalogMergeService & Provenance Contract.
"""

import copy
import os
import pytest

from services.catalog_parser_service import parse_catalog_csv
from services.catalog_merge_service import (
    CatalogMergeService,
    merge_catalogs,
    get_identity_key,
)

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "ARVENA_Upload_Ready_Catalog.csv"
)


def _get_parsed_arvena_records():
    assert os.path.exists(FIXTURE_PATH), f"Fixture not found at {FIXTURE_PATH}"
    with open(FIXTURE_PATH, "rb") as f:
        content = f.read()
    res = parse_catalog_csv(content)
    assert res.stats["accepted_records"] == 14
    return res.records


def test_1_empty_existing_plus_arvena_import():
    arvena_records = _get_parsed_arvena_records()
    src = {"source_type": "upload", "source_id": "arvena_catalog"}

    res = merge_catalogs([], arvena_records, src)
    assert res.stats["effective_records"] == 14
    assert res.stats["added_records"] == 14
    assert res.stats["product_count"] if "product_count" in res.stats else len([r for r in res.records if r["record_type"] == "product"]) == 11
    assert len([r for r in res.records if r["record_type"] == "bundle"]) == 3

    ergo_one = next(r for r in res.records if r["name"] == "Arvena Ergo One")
    assert ergo_one["price"] == 6900.0
    assert ergo_one["currency"] == "EGP"
    assert ergo_one["provenance"]["sources"][0]["source_id"] == "arvena_catalog"
    assert ergo_one["provenance"]["field_sources"]["price"][0]["source_id"] == "arvena_catalog"


def test_2_identical_same_source_reupload():
    arvena_records = _get_parsed_arvena_records()
    src = {"source_type": "upload", "source_id": "arvena_catalog"}

    res1 = merge_catalogs([], arvena_records, src)
    assert len(res1.records) == 14

    res2 = merge_catalogs(res1.records, arvena_records, src)
    assert res2.stats["effective_records"] == 14
    assert res2.stats["added_records"] == 0
    assert len(res2.records) == 14

    ergo_one = next(r for r in res2.records if r["name"] == "Arvena Ergo One")
    # Provenance source list should not duplicate source references
    sources = ergo_one["provenance"]["sources"]
    assert len(sources) == 1
    assert sources[0]["source_id"] == "arvena_catalog"


def test_3_same_source_price_update():
    arvena_records = _get_parsed_arvena_records()
    src = {"source_type": "upload", "source_id": "arvena_catalog"}
    res1 = merge_catalogs([], arvena_records, src)

    updated_records = copy.deepcopy(arvena_records)
    ergo_one_inc = next(r for r in updated_records if r.get("sku") == "AR-CHR-001")
    ergo_one_inc["price"] = 7200.0

    res2 = merge_catalogs(res1.records, updated_records, src)
    assert len(res2.records) == 14
    ergo_one = next(r for r in res2.records if r.get("sku") == "AR-CHR-001")
    assert ergo_one["price"] == 7200.0
    assert ergo_one["provenance"]["field_sources"]["price"][0]["source_id"] == "arvena_catalog"


def test_4_manual_price_override_with_imported_richness():
    manual_records = [
        {
            "record_type": "product",
            "sku": "AR-CHR-001",
            "name": "Arvena Ergo One",
            "price": 7000.0,
        }
    ]
    arvena_records = _get_parsed_arvena_records()
    upload_src = {"source_type": "upload", "source_id": "arvena_catalog"}
    manual_src = {"source_type": "manual", "source_id": "settings_manual"}

    res = merge_catalogs(manual_records, arvena_records, upload_src, existing_source=manual_src)
    ergo_one = next(r for r in res.records if r.get("sku") == "AR-CHR-001")

    # Manual price overrides upload price
    assert ergo_one["price"] == 7000.0
    assert ergo_one["provenance"]["field_sources"]["price"][0]["source_id"] == "settings_manual"

    # Upload fills missing manual fields & rich metadata survives
    assert ergo_one["stock"] == 18
    assert ergo_one["provenance"]["field_sources"]["stock"][0]["source_id"] == "arvena_catalog"
    assert ergo_one["warranty"] == "24 شهر"
    assert len(ergo_one["quantity_discounts"]) == 3


def test_5_manual_missing_field_filled_by_upload():
    manual_records = [
        {
            "record_type": "product",
            "sku": "AR-CHR-001",
            "name": "Arvena Ergo One",
            "price": None,
        }
    ]
    arvena_records = _get_parsed_arvena_records()
    upload_src = {"source_type": "upload", "source_id": "arvena_catalog"}

    res = merge_catalogs(manual_records, arvena_records, upload_src)
    ergo_one = next(r for r in res.records if r.get("sku") == "AR-CHR-001")

    assert ergo_one["price"] == 6900.0
    assert ergo_one["provenance"]["field_sources"]["price"][0]["source_id"] == "arvena_catalog"


def test_6_no_sku_cross_source_safety():
    manual_rec = [{"name": "Ergo Chair", "price": 5000.0}]
    upload_rec = [{"name": "Ergo Chair", "price": 4500.0}]

    res = merge_catalogs(
        manual_rec,
        upload_rec,
        incoming_source={"source_type": "upload", "source_id": "supplier_catalog"},
        existing_source={"source_type": "manual", "source_id": "manual_entry"},
    )

    # Different sources without SKU must NOT auto-merge by name similarity
    assert len(res.records) == 2
    names = [r["name"] for r in res.records]
    assert names == ["Ergo Chair", "Ergo Chair"]


def test_7_upload_vs_upload_same_sku_conflict():
    rec_a = [{"sku": "SKU-100", "name": "Desk", "price": 5000.0}]
    rec_b = [{"sku": "SKU-100", "name": "Desk", "price": 5500.0}]

    res1 = merge_catalogs([], rec_a, {"source_type": "upload", "source_id": "src_a"})
    res2 = merge_catalogs(res1.records, rec_b, {"source_type": "upload", "source_id": "src_b"})

    assert len(res2.records) == 1
    assert res2.records[0]["price"] == 5000.0  # Retains first seen
    conflict_issues = [i for i in res2.issues if i["code"] == "CONFLICTING_SOURCE_VALUE"]
    assert len(conflict_issues) == 1
    assert conflict_issues[0]["field"] == "price"


def test_8_product_vs_bundle_same_sku_conflict():
    prod = [{"record_type": "product", "sku": "COMBO-1", "name": "Combo Pack", "price": 1000.0}]
    bndl = [{"record_type": "bundle", "sku": "COMBO-1", "name": "Combo Pack", "price": 1000.0}]

    res1 = merge_catalogs([], prod, {"source_type": "upload", "source_id": "src_a"})
    res2 = merge_catalogs(res1.records, bndl, {"source_type": "upload", "source_id": "src_b"})

    assert len(res2.records) == 1
    type_conflicts = [i for i in res2.issues if i["code"] == "RECORD_TYPE_CONFLICT"]
    assert len(type_conflicts) == 1


def test_9_duplicate_sku_in_same_batch():
    batch = [
        {"sku": "DUP-01", "name": "Chair V1", "price": 1000.0},
        {"sku": "DUP-01", "name": "Chair V2", "price": 1200.0},
    ]
    res = merge_catalogs([], batch, {"source_type": "upload", "source_id": "batch_upload"})

    assert len(res.records) == 1
    assert res.stats["duplicate_records"] == 1
    dup_issues = [i for i in res.issues if i["code"] == "DUPLICATE_SOURCE_RECORD"]
    assert len(dup_issues) == 1


def test_10_legacy_products_data_record_compatibility():
    legacy_record = {"name": "Old Legacy Chair", "price": 3000.0, "custom_field": "Val123"}
    res = merge_catalogs(
        [legacy_record],
        [],
        incoming_source={"source_type": "upload", "source_id": "dummy"},
    )

    assert len(res.records) == 1
    rec = res.records[0]
    assert rec["name"] == "Old Legacy Chair"
    assert rec["price"] == 3000.0
    assert rec["provenance"]["sources"][0]["source_id"] == "legacy_manual"
    assert rec["provenance"]["sources"][0]["source_type"] == "manual"
    assert rec["extra_fields"]["custom_field"] == "Val123"


def test_11_field_provenance_correctness():
    manual = [{"sku": "PROV-1", "name": "Manual Name", "price": 100.0}]
    upload = [{"sku": "PROV-1", "name": "Upload Name", "stock": 50}]

    res = merge_catalogs(
        manual,
        upload,
        incoming_source={"source_type": "upload", "source_id": "up1"},
        existing_source={"source_type": "manual", "source_id": "man1"},
    )
    rec = res.records[0]

    assert rec["provenance"]["field_sources"]["name"][0]["source_id"] == "man1"
    assert rec["provenance"]["field_sources"]["price"][0]["source_id"] == "man1"
    assert rec["provenance"]["field_sources"]["stock"][0]["source_id"] == "up1"


def test_12_source_list_deduplication():
    records = [{"sku": "SKU-DEDUP", "name": "Item", "price": 10.0}]
    src = {"source_type": "upload", "source_id": "up_same"}

    r1 = merge_catalogs([], records, src)
    r2 = merge_catalogs(r1.records, records, src)
    r3 = merge_catalogs(r2.records, records, src)

    sources = r3.records[0]["provenance"]["sources"]
    assert len(sources) == 1
    assert sources[0]["source_id"] == "up_same"


def test_13_list_field_deterministic_union():
    rec_a = [{"sku": "L1", "name": "Item", "colors": ["Red", "Blue"]}]
    rec_b = [{"sku": "L1", "name": "Item", "colors": ["blue", "Green"]}]

    res = merge_catalogs(
        rec_a,
        rec_b,
        incoming_source={"source_type": "upload", "source_id": "src_b"},
        existing_source={"source_type": "upload", "source_id": "src_a"},
    )
    colors = res.records[0]["colors"]
    assert colors == ["Red", "Blue", "Green"]


def test_14_quantity_discount_conflict_behavior():
    t_a = [{"sku": "QD-1", "name": "Item", "quantity_discounts": [{"min_qty": 5, "max_qty": 10, "discount_pct": 10.0}]}]
    t_b = [{"sku": "QD-1", "name": "Item", "quantity_discounts": [{"min_qty": 5, "max_qty": 10, "discount_pct": 15.0}]}]

    res = merge_catalogs(
        t_a,
        t_b,
        incoming_source={"source_type": "upload", "source_id": "src_b"},
        existing_source={"source_type": "upload", "source_id": "src_a"},
    )

    rec = res.records[0]
    assert rec["quantity_discounts"][0]["discount_pct"] == 10.0
    issues = [i for i in res.issues if i["code"] == "CONFLICTING_SOURCE_VALUE"]
    assert len(issues) == 1


def test_15_extra_fields_preservation():
    rec = [{"sku": "EXTRA-1", "name": "Item", "extra_fields": {"vendor": "Acme", "weight": "2kg"}}]
    res = merge_catalogs([], rec, {"source_type": "upload", "source_id": "supplier_catalog"})

    assert res.records[0]["extra_fields"] == {"vendor": "Acme", "weight": "2kg"}


def test_16_missing_incoming_values_do_not_erase_existing_non_empty_values():
    existing = [{"sku": "ERASE-1", "name": "Item", "warranty": "1 Year", "price": 500.0}]
    incoming = [{"sku": "ERASE-1", "name": "Item", "warranty": None, "price": None}]

    res = merge_catalogs(existing, incoming, {"source_type": "upload", "source_id": "reimport"})
    rec = res.records[0]

    assert rec["warranty"] == "1 Year"
    assert rec["price"] == 500.0


def test_17_missing_record_on_reupload_is_not_deleted():
    existing = [
        {"sku": "KEEP-1", "name": "Item 1", "price": 100.0},
        {"sku": "KEEP-2", "name": "Item 2", "price": 200.0},
    ]
    incoming_only_one = [{"sku": "KEEP-1", "name": "Item 1 Updated", "price": 110.0}]

    res = merge_catalogs(existing, incoming_only_one, {"source_type": "upload", "source_id": "reimport"})
    assert len(res.records) == 2
    skus = [r["sku"] for r in res.records]
    assert skus == ["KEEP-1", "KEEP-2"]


def test_18_input_objects_are_not_mutated():
    existing = [{"sku": "MUT-1", "name": "Orig Name", "colors": ["Red"]}]
    incoming = [{"sku": "MUT-1", "name": "New Name", "colors": ["Blue"]}]

    existing_snapshot = copy.deepcopy(existing)
    incoming_snapshot = copy.deepcopy(incoming)

    _ = merge_catalogs(existing, incoming, {"source_type": "upload", "source_id": "up"})

    assert existing == existing_snapshot
    assert incoming == incoming_snapshot


def test_19_deterministic_repeated_execution():
    existing = [{"sku": "DET-1", "name": "Item", "price": 100.0}]
    incoming = [{"sku": "DET-1", "name": "Item", "price": 150.0}]
    src = {"source_type": "upload", "source_id": "up"}

    r1 = merge_catalogs(existing, incoming, src)
    r2 = merge_catalogs(existing, incoming, src)

    assert r1.to_dict() == r2.to_dict()


def test_20_stable_output_ordering():
    existing = [
        {"sku": "SKU-B", "name": "Item B"},
        {"sku": "SKU-A", "name": "Item A"},
    ]
    incoming = [
        {"sku": "SKU-C", "name": "Item C"},
        {"sku": "SKU-A", "name": "Item A Updated"},
    ]

    res = merge_catalogs(existing, incoming, {"source_type": "upload", "source_id": "up"})
    skus = [r["sku"] for r in res.records]
    # Existing order preserved first, then new items appended in incoming order
    assert skus == ["SKU-B", "SKU-A", "SKU-C"]


def test_21_invalid_source_descriptor():
    records = [{"sku": "INV-1", "name": "Item"}]
    res = merge_catalogs([], records, {"invalid_key": 123})

    assert len(res.records) == 0
    errs = [i for i in res.issues if i["code"] == "INVALID_SOURCE_DESCRIPTOR"]
    assert len(errs) == 1


def test_22_real_arvena_fixture_read_through_existing_parser():
    arvena_records = _get_parsed_arvena_records()
    assert len(arvena_records) == 14


# ----------------------------------------------------------------------
# Mandatory Ticket Closure Focused Tests
# ----------------------------------------------------------------------

def test_invalid_upload_source_id_fails_closed():
    res = merge_catalogs([], [{"sku": "I1", "name": "Item"}], {"source_type": "upload", "source_id": ""})
    assert len(res.records) == 0
    assert any(i["code"] == "INVALID_SOURCE_DESCRIPTOR" for i in res.issues)
    assert res.stats["added_records"] == 0
    assert res.stats["effective_records"] == 0


def test_missing_upload_source_id_fails_closed():
    res = merge_catalogs([], [{"sku": "I2", "name": "Item"}], {"source_type": "upload"})
    assert len(res.records) == 0
    assert any(i["code"] == "INVALID_SOURCE_DESCRIPTOR" for i in res.issues)


def test_invalid_source_type_fails_closed():
    res = merge_catalogs([], [{"sku": "I3", "name": "Item"}], "not_a_dict")
    assert len(res.records) == 0
    assert any(i["code"] == "INVALID_SOURCE_DESCRIPTOR" for i in res.issues)


def test_invalid_source_cannot_escalate_to_manual_precedence():
    existing = [
        {
            "record_type": "product",
            "sku": "AR-CHR-001",
            "name": "Arvena Ergo One",
            "price": 6900.0,
        }
    ]
    existing_src = {"source_type": "upload", "source_id": "trusted_catalog"}
    malformed_inc_src = {"source_type": "upload", "source_id": ""}
    incoming = [
        {
            "record_type": "product",
            "sku": "AR-CHR-001",
            "name": "Arvena Ergo One",
            "price": 9000.0,
        }
    ]

    res = merge_catalogs(existing, incoming, malformed_inc_src, existing_source=existing_src)

    assert len(res.records) == 1
    rec = res.records[0]
    assert rec["price"] == 6900.0
    assert any(i["code"] == "INVALID_SOURCE_DESCRIPTOR" for i in res.issues)
    sources = rec["provenance"]["sources"]
    assert len(sources) == 1
    assert sources[0]["source_id"] == "trusted_catalog"
    assert all(s["source_id"] != "legacy_manual" for s in sources)


def test_legacy_existing_record_still_uses_legacy_manual_compatibility():
    existing_legacy = [{"name": "Legacy Chair", "price": 5000.0}]
    res = merge_catalogs(existing_legacy, [], incoming_source={"source_type": "upload", "source_id": "dummy"})

    assert len(res.records) == 1
    rec = res.records[0]
    assert rec["provenance"]["sources"][0]["source_id"] == "legacy_manual"
    assert rec["provenance"]["sources"][0]["source_type"] == "manual"


def test_composite_colors_provenance_tracks_all_actual_contributors():
    manual_rec = [{"sku": "C1", "name": "Chair", "colors": ["Black"]}]
    upload_rec = [{"sku": "C1", "name": "Chair", "colors": ["Gray"]}]

    res = merge_catalogs(
        manual_rec,
        upload_rec,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "man_src"},
    )

    rec = res.records[0]
    assert rec["colors"] == ["Black", "Gray"]
    color_sources = rec["provenance"]["field_sources"]["colors"]
    assert len(color_sources) == 2
    assert color_sources[0] == {"source_type": "manual", "source_id": "man_src"}
    assert color_sources[1] == {"source_type": "upload", "source_id": "up_src"}


def test_duplicate_equivalent_list_value_does_not_create_false_contributor():
    manual_rec = [{"sku": "C2", "name": "Chair", "colors": ["Black"]}]
    upload_rec = [{"sku": "C2", "name": "Chair", "colors": ["black"]}]

    res = merge_catalogs(
        manual_rec,
        upload_rec,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "man_src"},
    )

    rec = res.records[0]
    assert rec["colors"] == ["Black"]
    color_sources = rec["provenance"]["field_sources"]["colors"]
    assert len(color_sources) == 1
    assert color_sources[0] == {"source_type": "manual", "source_id": "man_src"}


def test_aliases_composite_provenance():
    manual_rec = [{"sku": "A1", "name": "Chair", "aliases": ["Desk Chair"]}]
    upload_rec = [{"sku": "A1", "name": "Chair", "aliases": ["Office Chair"]}]

    res = merge_catalogs(
        manual_rec,
        upload_rec,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "man_src"},
    )

    rec = res.records[0]
    assert rec["aliases"] == ["Desk Chair", "Office Chair"]
    alias_sources = rec["provenance"]["field_sources"]["aliases"]
    assert len(alias_sources) == 2
    assert alias_sources[0] == {"source_type": "manual", "source_id": "man_src"}
    assert alias_sources[1] == {"source_type": "upload", "source_id": "up_src"}


def test_quantity_discount_non_conflicting_multi_source_provenance():
    src_a_rec = [{"sku": "QD-NC", "name": "Item", "quantity_discounts": [{"min_qty": 3, "max_qty": 4, "discount_pct": 5.0}]}]
    src_b_rec = [{"sku": "QD-NC", "name": "Item", "quantity_discounts": [{"min_qty": 10, "max_qty": None, "discount_pct": 12.0}]}]

    res = merge_catalogs(
        src_a_rec,
        src_b_rec,
        incoming_source={"source_type": "upload", "source_id": "src_b"},
        existing_source={"source_type": "upload", "source_id": "src_a"},
    )

    rec = res.records[0]
    assert len(rec["quantity_discounts"]) == 2
    qd_sources = rec["provenance"]["field_sources"]["quantity_discounts"]
    assert len(qd_sources) == 2
    assert qd_sources[0]["source_id"] == "src_a"
    assert qd_sources[1]["source_id"] == "src_b"


def test_quantity_discount_conflict_provenance_follows_effective_value():
    src_a_rec = [{"sku": "QD-CONF", "name": "Item", "quantity_discounts": [{"min_qty": 3, "max_qty": 4, "discount_pct": 5.0}]}]
    src_b_rec = [{"sku": "QD-CONF", "name": "Item", "quantity_discounts": [{"min_qty": 3, "max_qty": 4, "discount_pct": 7.0}]}]

    res = merge_catalogs(
        src_a_rec,
        src_b_rec,
        incoming_source={"source_type": "upload", "source_id": "src_b"},
        existing_source={"source_type": "upload", "source_id": "src_a"},
    )

    rec = res.records[0]
    assert rec["quantity_discounts"][0]["discount_pct"] == 5.0
    qd_sources = rec["provenance"]["field_sources"]["quantity_discounts"]
    assert len(qd_sources) == 1
    assert qd_sources[0]["source_id"] == "src_a"


def test_extra_fields_multi_source_provenance():
    man_rec = [{"sku": "EF-1", "name": "Item", "extra_fields": {"vip_note": "Yes"}}]
    up_rec = [{"sku": "EF-1", "name": "Item", "extra_fields": {"material": "Mesh"}}]

    res = merge_catalogs(
        man_rec,
        up_rec,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "man_src"},
    )

    rec = res.records[0]
    assert rec["extra_fields"] == {"vip_note": "Yes", "material": "Mesh"}
    assert rec["provenance"]["field_sources"]["extra_fields.vip_note"][0]["source_id"] == "man_src"
    assert rec["provenance"]["field_sources"]["extra_fields.material"][0]["source_id"] == "up_src"


def test_extra_fields_conflict_provenance_follows_selected_value():
    man_rec = [{"sku": "EF-2", "name": "Item", "extra_fields": {"material": "Leather"}}]
    up_rec = [{"sku": "EF-2", "name": "Item", "extra_fields": {"material": "Mesh"}}]

    res = merge_catalogs(
        man_rec,
        up_rec,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "man_src"},
    )

    rec = res.records[0]
    assert rec["extra_fields"]["material"] == "Leather"
    mat_sources = rec["provenance"]["field_sources"]["extra_fields.material"]
    assert len(mat_sources) == 1
    assert mat_sources[0]["source_id"] == "man_src"


def test_same_source_reupload_does_not_duplicate_field_provenance():
    records = [{"sku": "RE-1", "name": "Item", "price": 100.0, "colors": ["Red"]}]
    src = {"source_type": "upload", "source_id": "up_src"}

    r1 = merge_catalogs([], records, src)
    r2 = merge_catalogs(r1.records, records, src)

    rec = r2.records[0]
    assert len(rec["provenance"]["sources"]) == 1
    assert len(rec["provenance"]["field_sources"]["price"]) == 1
    assert len(rec["provenance"]["field_sources"]["colors"]) == 1


def test_scalar_override_provenance_names_only_effective_supplier():
    manual = [{"sku": "SC-1", "name": "Item", "price": 7000.0}]
    upload = [{"sku": "SC-1", "name": "Item", "price": 6900.0}]

    res = merge_catalogs(
        manual,
        upload,
        incoming_source={"source_type": "upload", "source_id": "up_src"},
        existing_source={"source_type": "manual", "source_id": "settings_manual"},
    )

    rec = res.records[0]
    assert rec["price"] == 7000.0
    price_sources = rec["provenance"]["field_sources"]["price"]
    assert len(price_sources) == 1
    assert price_sources[0]["source_id"] == "settings_manual"
