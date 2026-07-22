import io
import json
import os
from pathlib import PurePath
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import CompanyKnowledge, get_db
from routers.auth import get_current_user
from services.catalog_merge_service import merge_catalogs
from services.catalog_parser_service import parse_catalog_csv, parse_catalog_xlsx


router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
MAX_CATALOG_UPLOAD_BYTES = int(os.getenv("CATALOG_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))
MAX_XLSX_UNCOMPRESSED_BYTES = int(os.getenv("CATALOG_XLSX_MAX_UNCOMPRESSED_BYTES", str(20 * 1024 * 1024)))


def _validate_catalog_upload(file: UploadFile, content: bytes) -> str:
    filename = (file.filename or "").strip()
    if not filename or len(filename) > 160 or PurePath(filename).name != filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid catalog file name.")
    extension = os.path.splitext(filename.casefold())[1]
    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Catalog import supports CSV or XLSX files.")
    mime = (file.content_type or "application/octet-stream").split(";", 1)[0].casefold()
    allowed = {
        ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "application/octet-stream"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip", "application/octet-stream"},
    }
    if mime not in allowed[extension]:
        raise HTTPException(status_code=400, detail="Catalog MIME type does not match its file extension.")
    if not content:
        raise HTTPException(status_code=400, detail="Catalog file is empty.")
    if extension == ".csv" and b"\x00" in content:
        raise HTTPException(status_code=400, detail="CSV catalog contains binary data.")
    if extension == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                total = sum(max(entry.file_size, 0) for entry in entries)
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise HTTPException(status_code=400, detail="Invalid XLSX catalog.")
                if len(entries) > 3000 or total > MAX_XLSX_UNCOMPRESSED_BYTES or total > max(len(content), 1) * 100:
                    raise HTTPException(status_code=413, detail="XLSX catalog expands beyond the safe processing limit.")
                for entry in entries:
                    normalized = entry.filename.replace("\\", "/").casefold()
                    if normalized.startswith("/") or "../" in normalized or normalized.endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".vbs")):
                        raise HTTPException(status_code=400, detail="Unsafe XLSX content is not allowed.")
        except HTTPException:
            raise
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid XLSX catalog.")
    return extension


async def _parse_upload(file: UploadFile):
    content = await file.read(MAX_CATALOG_UPLOAD_BYTES + 1)
    if len(content) > MAX_CATALOG_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Catalog file exceeds the 5MB safe limit.")
    extension = _validate_catalog_upload(file, content)
    result = parse_catalog_csv(content) if extension == ".csv" else parse_catalog_xlsx(content)
    return result


def _existing_records(knowledge: CompanyKnowledge | None) -> list[dict]:
    if not knowledge or not knowledge.products_data:
        return []
    try:
        parsed = json.loads(knowledge.products_data)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


@router.get("")
def list_catalog(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    category: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == current_user["company_id"]).first()
    records = _existing_records(knowledge)
    if category:
        records = [row for row in records if str(row.get("category") or "").casefold() == category.casefold()]
    start = (page - 1) * page_size
    return {
        "success": True,
        "total": len(records),
        "page": page,
        "page_size": page_size,
        "records": records[start:start + page_size],
        "categories": sorted({str(row.get("category")) for row in records if row.get("category")}),
    }


@router.post("/import")
async def import_catalog(
    file: UploadFile = File(...),
    commit: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    parse_result = await _parse_upload(file)
    errors = [issue for issue in parse_result.issues if issue.get("severity") == "error"]
    preview = {
        "stats": parse_result.stats,
        "issues": parse_result.issues,
        "records": parse_result.records[:200],
        "truncated": len(parse_result.records) > 200,
    }
    if not commit:
        return {"success": not errors, "committed": False, "preview": preview}
    if errors or not parse_result.records:
        raise HTTPException(status_code=400, detail={"message": "Catalog import has blocking validation errors.", "preview": preview})

    company_id = current_user["company_id"]
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if not knowledge:
        knowledge = CompanyKnowledge(company_id=company_id, products_data="[]")
        db.add(knowledge)
        db.flush()
    source = {
        "source_type": "upload",
        "source_id": f"catalog_upload_{uuid.uuid4().hex}",
        "source_label": (file.filename or "catalog")[:160],
    }
    merged = merge_catalogs(_existing_records(knowledge), parse_result.records, source)
    merge_errors = [issue for issue in merged.issues if issue.get("severity") == "error"]
    if merge_errors:
        raise HTTPException(status_code=409, detail={"message": "Catalog merge has blocking conflicts.", "issues": merged.issues})
    knowledge.products_data = json.dumps(merged.records, ensure_ascii=False)
    from services.workspace_suggestion_service import invalidate_company_suggestions
    invalidate_company_suggestions(db, company_id, "catalog_changed")
    db.commit()
    try:
        from services.pilot_telemetry_service import record_pilot_event
        record_pilot_event(
            db,
            event_name="catalog_first_valid_product",
            company_id=company_id,
            actor_type="owner",
            entity_id=company_id,
            source="catalog_import",
        )
    except Exception:
        db.rollback()
    return {
        "success": True,
        "committed": True,
        "preview": preview,
        "merge": {"stats": merged.stats, "issues": merged.issues, "effective_records": len(merged.records)},
    }
