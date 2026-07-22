import json
from typing import Optional, Any, Dict, List
from fastapi import HTTPException

LEGACY_SHALLOW_EDITOR_OWNED_FIELDS = {"name", "price", "id"}

RICH_METADATA_FIELDS = {
    "provenance",
    "sku",
    "record_type",
    "stock",
    "warranty",
    "colors",
    "aliases",
    "installation",
    "installation_fee",
    "quantity_discounts",
    "components_text",
    "extra_fields",
    "currency",
}


def is_protected_record(record: Any) -> bool:
    """
    Determines if a single catalog record contains data that cannot be safely and
    completely represented and round-tripped by the current shallow Settings product editor.
    """
    if isinstance(record, str):
        # Legacy simple catalog text/string entries are shallow
        return False
    if not isinstance(record, dict):
        # Unexpected/malformed record structure cannot be proven safe -> protected
        return True

    for key, val in record.items():
        if key not in LEGACY_SHALLOW_EDITOR_OWNED_FIELDS:
            if key in ("record_type", "sku", "currency", "provenance"):
                return True
            if val is not None and val != "" and val != [] and val != {}:
                return True

    return False


def is_protected_catalog(existing_products_raw: Optional[str]) -> bool:
    """
    Returns True if the existing persisted catalog is protected from mutation by the shallow Settings editor.
    A catalog is protected if it contains any record that cannot be safely represented without data loss,
    or if the existing catalog is malformed JSON such that safe replacement cannot be proven.
    """
    if not existing_products_raw or not isinstance(existing_products_raw, str):
        return False

    raw_trimmed = existing_products_raw.strip()
    if not raw_trimmed or raw_trimmed == "[]":
        return False

    try:
        data = json.loads(raw_trimmed)
    except Exception:
        # Existing catalog is malformed JSON -> fail closed (protect)
        return True

    if not isinstance(data, list):
        return True

    return any(is_protected_record(item) for item in data)


def is_rich_catalog_record(record: Any) -> bool:
    """Returns True if record has canonical metadata beyond simple legacy name/price."""
    return is_protected_record(record)


def is_rich_catalog(products_data_raw: Optional[str]) -> bool:
    """Returns True if products_data_raw parses into a list containing any rich record."""
    return is_protected_catalog(products_data_raw)


def validate_catalog_replacement(existing_products_raw: Optional[str], incoming_products_raw: Optional[str]) -> None:
    """
    Validates explicit product replacements against protected catalogs.
    Fails closed with UNSAFE_CATALOG_REPLACEMENT if an explicit products mutation is attempted
    against a protected existing catalog, or if incoming payload format is invalid.
    """
    # Omitted or explicit null incoming products payload is always safe (preserves existing)
    if incoming_products_raw is None:
        return

    # Check if the existing persisted catalog is protected
    if is_protected_catalog(existing_products_raw):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSAFE_CATALOG_REPLACEMENT",
                "message": "The existing structured catalog cannot be modified through the current Settings product editor."
            }
        )

    # For legacy shallow catalogs, validate incoming JSON payload syntax if provided
    try:
        incoming = json.loads(incoming_products_raw) if isinstance(incoming_products_raw, str) else incoming_products_raw
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSAFE_CATALOG_REPLACEMENT",
                "message": "Invalid products_data JSON payload format."
            }
        )

    if not isinstance(incoming, list):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSAFE_CATALOG_REPLACEMENT",
                "message": "Invalid products_data JSON payload format."
            }
        )

