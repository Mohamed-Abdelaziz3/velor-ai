"""
Pure, deterministic service for merging catalog records and tracking provenance.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from services.product_context_service import _clean_name


@dataclass
class CatalogMergeIssue:
    severity: str  # "error" | "warning" | "info"
    code: str
    identity_key: Optional[str] = None
    field: Optional[str] = None
    source_ids: Optional[List[str]] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.identity_key is not None:
            res["identity_key"] = self.identity_key
        if self.field is not None:
            res["field"] = self.field
        if self.source_ids is not None:
            res["source_ids"] = list(self.source_ids)
        return res


@dataclass
class CatalogMergeStats:
    existing_records_seen: int = 0
    incoming_records_seen: int = 0
    effective_records: int = 0
    added_records: int = 0
    updated_records: int = 0
    merged_records: int = 0
    duplicate_records: int = 0
    conflict_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "existing_records_seen": self.existing_records_seen,
            "incoming_records_seen": self.incoming_records_seen,
            "effective_records": self.effective_records,
            "added_records": self.added_records,
            "updated_records": self.updated_records,
            "merged_records": self.merged_records,
            "duplicate_records": self.duplicate_records,
            "conflict_count": self.conflict_count,
        }


@dataclass
class CatalogMergeResult:
    records: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": self.records,
            "issues": self.issues,
            "stats": self.stats,
        }


DEFAULT_LEGACY_SOURCE: Dict[str, Any] = {
    "source_type": "manual",
    "source_id": "legacy_manual",
    "source_label": "Legacy Manual Data",
}

_CANONICAL_SCALAR_FIELDS = [
    "name",
    "category",
    "description",
    "price",
    "currency",
    "stock",
    "warranty",
    "installation",
    "installation_fee",
    "components_text",
    "notes",
]

_CANONICAL_LIST_FIELDS = ["colors", "aliases"]


def _source_rank(source_type: str) -> int:
    return 2 if source_type == "manual" else 1


def _validate_source_descriptor(src: Any) -> Tuple[Dict[str, Any], Optional[CatalogMergeIssue]]:
    if not isinstance(src, dict):
        return (
            DEFAULT_LEGACY_SOURCE,
            CatalogMergeIssue(
                severity="error",
                code="INVALID_SOURCE_DESCRIPTOR",
                message="Source descriptor must be a dictionary.",
            ),
        )
    source_id = str(src.get("source_id") or "").strip()
    if not source_id:
        return (
            DEFAULT_LEGACY_SOURCE,
            CatalogMergeIssue(
                severity="error",
                code="INVALID_SOURCE_DESCRIPTOR",
                message="Source descriptor requires non-empty source_id.",
            ),
        )
    source_type = str(src.get("source_type") or "upload").strip().casefold()
    if source_type not in ("manual", "upload"):
        source_type = "upload"

    source_label = src.get("source_label")
    if source_label is not None:
        source_label = str(source_label).strip() or None

    return (
        {
            "source_type": source_type,
            "source_id": source_id,
            "source_label": source_label,
        },
        None,
    )


def get_identity_key(record: Dict[str, Any], source: Dict[str, Any]) -> str:
    raw_sku = record.get("sku")
    if raw_sku is not None:
        sku_str = str(raw_sku).strip()
        if sku_str:
            return f"sku::{sku_str.upper()}"

    src_type = str(source.get("source_type") or "manual").strip().casefold()
    src_id = str(source.get("source_id") or "legacy_manual").strip()
    rec_type = str(record.get("record_type") or "product").strip().casefold()
    name_norm = _clean_name(record.get("name")).casefold()
    cat_norm = _clean_name(record.get("category")).casefold()
    return f"nosku::{src_type}::{src_id}::{rec_type}::{cat_norm}::{name_norm}"


def _is_non_empty(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return True
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return bool(val)


def _canonicalize_quantity_discounts(raw_discounts: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_discounts, list):
        return []
    result = []
    for d in raw_discounts:
        if not isinstance(d, dict):
            continue
        min_q = d.get("min_qty")
        if min_q is None:
            continue
        try:
            min_qty = int(min_q)
        except (ValueError, TypeError):
            continue

        max_q = d.get("max_qty")
        max_qty: Optional[int] = None
        if max_q is not None:
            try:
                max_qty = int(max_q)
            except (ValueError, TypeError):
                max_qty = None

        disc_p = d.get("discount_pct")
        if disc_p is None:
            disc_p = d.get("discount_percent")
        if disc_p is None:
            continue
        try:
            disc_pct = float(disc_p)
        except (ValueError, TypeError):
            continue

        result.append(
            {
                "min_qty": min_qty,
                "max_qty": max_qty,
                "discount_pct": disc_pct,
            }
        )
    return result


class CatalogMergeService:
    @staticmethod
    def merge(
        existing_records: List[Dict[str, Any]],
        incoming_records: List[Dict[str, Any]],
        incoming_source: Dict[str, Any],
        existing_source: Optional[Dict[str, Any]] = None,
    ) -> CatalogMergeResult:
        issues: List[CatalogMergeIssue] = []

        # Validate incoming source
        inc_src, inc_err = _validate_source_descriptor(incoming_source)
        if inc_err:
            issues.append(inc_err)

        # Validate existing source
        ext_src, _ = _validate_source_descriptor(
            existing_source if existing_source is not None else DEFAULT_LEGACY_SOURCE
        )

        stats = CatalogMergeStats(
            existing_records_seen=len(existing_records),
            incoming_records_seen=len(incoming_records),
        )

        # Internal accumulated record state by identity_key
        # Preservation of identity key order: list of identity keys
        identity_order: List[str] = []
        existing_keys: Set[str] = set()
        records_state: Dict[str, Dict[str, Any]] = {}

        # ----------------------------------------------------
        # Helper to initialize or update internal record state
        # ----------------------------------------------------
        def _get_or_create_state(ident_key: str) -> Dict[str, Any]:
            if ident_key not in records_state:
                identity_order.append(ident_key)
                records_state[ident_key] = {
                    "identity_key": ident_key,
                    "record_type": None,
                    "record_type_source": None,
                    "sources_map": {},  # source_id -> source_dict
                    "field_values": {},  # field_name -> value
                    "field_sources": {},  # field_name -> {source_type, source_id}
                    "list_items": {},  # list_field -> [(cleaned_str, original_str, source_dict)]
                    "quantity_discounts": {},  # (min_qty, max_qty) -> (discount_pct, source_dict)
                    "extra_fields": {},  # key -> (value, source_dict)
                    "has_existing_contrib": False,
                    "has_incoming_contrib": False,
                    "is_updated": False,
                }
            return records_state[ident_key]

        def _add_source_contrib(
            state: Dict[str, Any],
            src_desc: Dict[str, Any],
            ident_key: str,
        ):
            s_id = src_desc["source_id"]
            if s_id not in state["sources_map"]:
                s_key = f"{s_id}::{ident_key}"
                state["sources_map"][s_id] = {
                    "source_type": src_desc["source_type"],
                    "source_id": s_id,
                    "source_label": src_desc.get("source_label"),
                    "source_record_key": s_key,
                }

        # ----------------------------------------------------
        # Helper to process one contribution from a record
        # ----------------------------------------------------
        def _apply_record_contribution(
            record: Dict[str, Any],
            src_desc: Dict[str, Any],
            is_incoming: bool,
        ):
            rec_copy = copy.deepcopy(record)
            prov = rec_copy.get("provenance")

            ident_key = get_identity_key(rec_copy, src_desc)
            state = _get_or_create_state(ident_key)

            if is_incoming:
                state["has_incoming_contrib"] = True
                if state["has_existing_contrib"]:
                    stats.merged_records += 1
            else:
                state["has_existing_contrib"] = True
                existing_keys.add(ident_key)

            # Register provenance sources if existing record had explicit provenance
            if isinstance(prov, dict) and isinstance(prov.get("sources"), list):
                for s in prov["sources"]:
                    if isinstance(s, dict) and s.get("source_id"):
                        _add_source_contrib(state, s, ident_key)
            else:
                _add_source_contrib(state, src_desc, ident_key)

            # Record type handling
            rec_type = str(rec_copy.get("record_type") or "product").strip().casefold()
            if rec_type not in ("product", "bundle"):
                rec_type = "product"

            if state["record_type"] is None:
                state["record_type"] = rec_type
                state["record_type_source"] = src_desc
            elif state["record_type"] != rec_type:
                issues.append(
                    CatalogMergeIssue(
                        severity="warning",
                        code="RECORD_TYPE_CONFLICT",
                        identity_key=ident_key,
                        source_ids=[
                            state["record_type_source"]["source_id"],
                            src_desc["source_id"],
                        ],
                        message=(
                            f"Record type conflict for SKU '{ident_key}': "
                            f"existing '{state['record_type']}' ({state['record_type_source']['source_id']}) "
                            f"vs incoming '{rec_type}' ({src_desc['source_id']})."
                        ),
                    )
                )
                stats.conflict_count += 1
                curr_rank = _source_rank(state["record_type_source"]["source_type"])
                inc_rank = _source_rank(src_desc["source_type"])
                if inc_rank > curr_rank:
                    state["record_type"] = rec_type
                    state["record_type_source"] = src_desc

            # Standard scalar fields
            for f in _CANONICAL_SCALAR_FIELDS:
                val = rec_copy.get(f)
                if not _is_non_empty(val):
                    continue

                curr_val = state["field_values"].get(f)
                curr_src_info = state["field_sources"].get(f)

                if curr_val is None or curr_src_info is None:
                    state["field_values"][f] = val
                    state["field_sources"][f] = {
                        "source_type": src_desc["source_type"],
                        "source_id": src_desc["source_id"],
                    }
                    if is_incoming and state["has_existing_contrib"]:
                        state["is_updated"] = True
                else:
                    curr_src_id = curr_src_info["source_id"]
                    curr_src_type = curr_src_info["source_type"]

                    if curr_src_id == src_desc["source_id"]:
                        # Same source update
                        if curr_val != val:
                            state["field_values"][f] = val
                            if is_incoming:
                                state["is_updated"] = True
                    else:
                        # Cross-source merge
                        curr_rank = _source_rank(curr_src_type)
                        inc_rank = _source_rank(src_desc["source_type"])

                        if inc_rank > curr_rank:
                            # Higher precedence (e.g. manual over upload)
                            state["field_values"][f] = val
                            state["field_sources"][f] = {
                                "source_type": src_desc["source_type"],
                                "source_id": src_desc["source_id"],
                            }
                            if is_incoming:
                                state["is_updated"] = True
                        elif inc_rank < curr_rank:
                            # Lower precedence, do not overwrite higher precedence
                            pass
                        else:
                            # Same rank (e.g. upload vs upload with different source_ids)
                            if curr_val != val:
                                issues.append(
                                    CatalogMergeIssue(
                                        severity="warning",
                                        code="CONFLICTING_SOURCE_VALUE",
                                        identity_key=ident_key,
                                        field=f,
                                        source_ids=[curr_src_id, src_desc["source_id"]],
                                        message=(
                                            f"Conflicting value for field '{f}' on '{ident_key}': "
                                            f"'{curr_val}' ({curr_src_id}) vs '{val}' ({src_desc['source_id']}). "
                                            f"Retaining existing value."
                                        ),
                                    )
                                )
                                stats.conflict_count += 1

            # List fields (colors, aliases)
            for lf in _CANONICAL_LIST_FIELDS:
                raw_list = rec_copy.get(lf)
                if not isinstance(raw_list, list):
                    continue
                if lf not in state["list_items"]:
                    state["list_items"][lf] = []

                existing_cf_set = {item[0] for item in state["list_items"][lf]}
                for item in raw_list:
                    item_str = str(item).strip()
                    if not item_str:
                        continue
                    cf = item_str.casefold()
                    if cf not in existing_cf_set:
                        existing_cf_set.add(cf)
                        state["list_items"][lf].append((cf, item_str, src_desc))

            # Quantity discounts
            qd_list = _canonicalize_quantity_discounts(rec_copy.get("quantity_discounts"))
            for qd in qd_list:
                tier_key = (qd["min_qty"], qd["max_qty"])
                new_pct = qd["discount_pct"]

                if tier_key not in state["quantity_discounts"]:
                    state["quantity_discounts"][tier_key] = (new_pct, src_desc)
                else:
                    curr_pct, curr_sd = state["quantity_discounts"][tier_key]
                    if curr_sd["source_id"] == src_desc["source_id"]:
                        state["quantity_discounts"][tier_key] = (new_pct, src_desc)
                    else:
                        curr_rank = _source_rank(curr_sd["source_type"])
                        inc_rank = _source_rank(src_desc["source_type"])
                        if inc_rank > curr_rank:
                            state["quantity_discounts"][tier_key] = (new_pct, src_desc)
                        elif inc_rank < curr_rank:
                            pass
                        else:
                            if curr_pct != new_pct:
                                issues.append(
                                    CatalogMergeIssue(
                                        severity="warning",
                                        code="CONFLICTING_SOURCE_VALUE",
                                        identity_key=ident_key,
                                        field="quantity_discounts",
                                        source_ids=[curr_sd["source_id"], src_desc["source_id"]],
                                        message=(
                                            f"Conflicting discount percentage for tier {tier_key} on '{ident_key}': "
                                            f"{curr_pct}% ({curr_sd['source_id']}) vs {new_pct}% ({src_desc['source_id']}). "
                                            f"Retaining existing discount."
                                        ),
                                    )
                                )
                                stats.conflict_count += 1

            # Extra fields
            extra = rec_copy.get("extra_fields")
            if not isinstance(extra, dict):
                # Also collect any top-level unknown non-canonical fields from legacy records
                extra = {}
                for k, v in rec_copy.items():
                    if k not in _CANONICAL_SCALAR_FIELDS and k not in _CANONICAL_LIST_FIELDS:
                        if k not in ("record_type", "sku", "quantity_discounts", "provenance", "extra_fields"):
                            if _is_non_empty(v):
                                extra[k] = v

            for ek, ev in extra.items():
                if not _is_non_empty(ev):
                    continue
                if ek not in state["extra_fields"]:
                    state["extra_fields"][ek] = (ev, src_desc)
                else:
                    curr_ev, curr_sd = state["extra_fields"][ek]
                    if curr_sd["source_id"] == src_desc["source_id"]:
                        state["extra_fields"][ek] = (ev, src_desc)
                    else:
                        curr_rank = _source_rank(curr_sd["source_type"])
                        inc_rank = _source_rank(src_desc["source_type"])
                        if inc_rank > curr_rank:
                            state["extra_fields"][ek] = (ev, src_desc)
                        elif inc_rank < curr_rank:
                            pass
                        else:
                            if curr_ev != ev:
                                issues.append(
                                    CatalogMergeIssue(
                                        severity="warning",
                                        code="CONFLICTING_SOURCE_VALUE",
                                        identity_key=ident_key,
                                        field=f"extra_fields.{ek}",
                                        source_ids=[curr_sd["source_id"], src_desc["source_id"]],
                                        message=(
                                            f"Conflicting value for extra field '{ek}' on '{ident_key}': "
                                            f"'{curr_ev}' ({curr_sd['source_id']}) vs '{ev}' ({src_desc['source_id']}). "
                                            f"Retaining existing value."
                                        ),
                                    )
                                )
                                stats.conflict_count += 1

        # ----------------------------------------------------
        # 1. Process existing records
        # ----------------------------------------------------
        for rec in existing_records:
            if not isinstance(rec, dict):
                continue
            # Extract source from record's provenance if present
            prov = rec.get("provenance")
            rec_src = ext_src
            if isinstance(prov, dict) and isinstance(prov.get("sources"), list) and len(prov["sources"]) > 0:
                first_src = prov["sources"][0]
                if isinstance(first_src, dict) and first_src.get("source_id"):
                    rec_src, _ = _validate_source_descriptor(first_src)

            _apply_record_contribution(rec, rec_src, is_incoming=False)

        # ----------------------------------------------------
        # 2. Process incoming records (ONLY if incoming_source is valid!)
        # ----------------------------------------------------
        if not inc_err:
            seen_incoming_batch_keys: Set[str] = set()
            for rec in incoming_records:
                if not isinstance(rec, dict):
                    continue
                ikey = get_identity_key(rec, inc_src)
                if ikey in seen_incoming_batch_keys:
                    issues.append(
                        CatalogMergeIssue(
                            severity="warning",
                            code="DUPLICATE_SOURCE_RECORD",
                            identity_key=ikey,
                            source_ids=[inc_src["source_id"]],
                            message=f"Duplicate record with identity '{ikey}' found in incoming batch '{inc_src['source_id']}'.",
                        )
                    )
                    stats.duplicate_records += 1
                seen_incoming_batch_keys.add(ikey)
                _apply_record_contribution(rec, inc_src, is_incoming=True)

        # ----------------------------------------------------
        # 3. Construct effective output records
        # ----------------------------------------------------
        effective_records: List[Dict[str, Any]] = []

        for ik in identity_order:
            st = records_state[ik]

            # Construct final canonical dict
            rec_type = st["record_type"] or "product"
            raw_sku = ik[5:] if ik.startswith("sku::") else None

            # Sources array (sorted: manual sources first, then upload by source_id)
            raw_sources = list(st["sources_map"].values())
            raw_sources.sort(
                key=lambda x: (
                    0 if x["source_type"] == "manual" else 1,
                    x["source_id"],
                )
            )

            # Field sources map (sorted by field name)
            field_sources_out: Dict[str, List[Dict[str, str]]] = {}

            record_out: Dict[str, Any] = {
                "record_type": rec_type,
                "sku": raw_sku,
                "name": st["field_values"].get("name") or "",
                "category": st["field_values"].get("category"),
                "description": st["field_values"].get("description"),
                "price": st["field_values"].get("price"),
                "currency": st["field_values"].get("currency"),
                "stock": st["field_values"].get("stock"),
                "colors": [],
                "warranty": st["field_values"].get("warranty"),
                "installation": st["field_values"].get("installation"),
                "installation_fee": st["field_values"].get("installation_fee"),
                "aliases": [],
                "quantity_discounts": [],
                "components_text": st["field_values"].get("components_text"),
                "notes": st["field_values"].get("notes"),
                "extra_fields": {},
            }

            def _format_source_list(sources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
                seen_ids: Set[str] = set()
                res: List[Dict[str, str]] = []
                for s in sources:
                    sid = s["source_id"]
                    if sid not in seen_ids:
                        seen_ids.add(sid)
                        res.append({
                            "source_type": s["source_type"],
                            "source_id": sid,
                        })
                res.sort(key=lambda x: (0 if x["source_type"] == "manual" else 1, x["source_id"]))
                return res

            # Copy field sources for non-empty scalar fields
            for f in _CANONICAL_SCALAR_FIELDS:
                if st["field_values"].get(f) is not None and f in st["field_sources"]:
                    sd = st["field_sources"][f]
                    field_sources_out[f] = _format_source_list([sd])

            # Reconstruct list fields
            for lf in _CANONICAL_LIST_FIELDS:
                items_tuples = st["list_items"].get(lf, [])
                record_out[lf] = [t[1] for t in items_tuples]
                if record_out[lf]:
                    lf_sources = [t[2] for t in items_tuples]
                    field_sources_out[lf] = _format_source_list(lf_sources)

            # Reconstruct quantity discounts
            qd_tuples = st["quantity_discounts"]
            sorted_tiers = sorted(qd_tuples.keys(), key=lambda t: (t[0], t[1] or 999999))
            res_qd = []
            qd_sources = []
            for t_key in sorted_tiers:
                pct, sd = qd_tuples[t_key]
                res_qd.append(
                    {
                        "min_qty": t_key[0],
                        "max_qty": t_key[1],
                        "discount_pct": pct,
                    }
                )
                qd_sources.append(sd)
            record_out["quantity_discounts"] = res_qd
            if res_qd:
                field_sources_out["quantity_discounts"] = _format_source_list(qd_sources)

            # Reconstruct extra fields
            res_extra = {}
            for ek, (ev, sd) in st["extra_fields"].items():
                res_extra[ek] = ev
                field_sources_out[f"extra_fields.{ek}"] = _format_source_list([sd])
            record_out["extra_fields"] = res_extra

            # Sort field sources alphabetically by key
            sorted_field_sources = {
                k: field_sources_out[k] for k in sorted(field_sources_out.keys())
            }

            record_out["provenance"] = {
                "sources": raw_sources,
                "field_sources": sorted_field_sources,
            }

            effective_records.append(record_out)

            # Update stats
            if ik not in existing_keys:
                stats.added_records += 1
            else:
                if st["is_updated"]:
                    stats.updated_records += 1

        stats.effective_records = len(effective_records)

        # Convert issue dataclasses to dicts
        issue_dicts = [iss.to_dict() for iss in issues]

        return CatalogMergeResult(
            records=effective_records,
            issues=issue_dicts,
            stats=stats.to_dict(),
        )


def merge_catalogs(
    existing_records: List[Dict[str, Any]],
    incoming_records: List[Dict[str, Any]],
    incoming_source: Dict[str, Any],
    existing_source: Optional[Dict[str, Any]] = None,
) -> CatalogMergeResult:
    return CatalogMergeService.merge(
        existing_records=existing_records,
        incoming_records=incoming_records,
        incoming_source=incoming_source,
        existing_source=existing_source,
    )
