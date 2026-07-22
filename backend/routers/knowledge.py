from datetime import datetime, timezone
import math
import os
from pathlib import PurePath
import re
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db, CompanyKnowledge, KnowledgeSource
from routers.auth import get_current_user
import io
import csv

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

MAX_UPLOAD_BYTES = int(os.getenv("KNOWLEDGE_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))
MAX_EXTRACTED_CHARS = int(os.getenv("KNOWLEDGE_EXTRACTED_MAX_CHARS", "250000"))
MAX_COMPILED_KNOWLEDGE_CHARS = int(os.getenv("KNOWLEDGE_COMPILED_MAX_CHARS", "500000"))
MAX_ARCHIVE_UNCOMPRESSED_BYTES = int(os.getenv("KNOWLEDGE_ARCHIVE_MAX_UNCOMPRESSED_BYTES", str(20 * 1024 * 1024)))
MAX_PDF_PAGES = int(os.getenv("KNOWLEDGE_PDF_MAX_PAGES", "200"))

ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/octet-stream"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
}


class KnowledgeSourceUpdate(BaseModel):
    active: bool


def _safe_source_filename(value: str | None) -> tuple[str, str]:
    filename = (value or "").strip()
    if not filename or len(filename) > 160:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    if PurePath(filename).name != filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    if any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    extension = os.path.splitext(filename.casefold())[1]
    if extension not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, DOCX, CSV, or TXT.")
    return filename, extension


def _validate_upload_bytes(extension: str, content_type: str | None, file_bytes: bytes) -> None:
    normalized_mime = (content_type or "application/octet-stream").split(";", 1)[0].strip().casefold()
    if normalized_mime not in ALLOWED_MIME_TYPES[extension]:
        raise HTTPException(status_code=400, detail="File type does not match the selected format.")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if extension == ".pdf" and not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF file.")
    if extension == ".docx":
        _validate_docx_archive(file_bytes)
    if extension in {".csv", ".txt"} and b"\x00" in file_bytes:
        raise HTTPException(status_code=400, detail="Text uploads cannot contain binary data.")


def _validate_docx_archive(file_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000:
                raise HTTPException(status_code=400, detail="Document archive contains too many entries.")
            total_size = sum(max(entry.file_size, 0) for entry in entries)
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES or total_size > max(len(file_bytes), 1) * 100:
                raise HTTPException(status_code=413, detail="Document expands beyond the safe processing limit.")
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise HTTPException(status_code=400, detail="Invalid DOCX file.")
            for entry in entries:
                normalized = entry.filename.replace("\\", "/")
                lowered = normalized.casefold()
                if normalized.startswith("/") or "../" in normalized or lowered.endswith(("vbaproject.bin", ".exe", ".dll", ".js", ".vbs")):
                    raise HTTPException(status_code=400, detail="Unsafe content is not allowed in DOCX files.")
    except HTTPException:
        raise
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid DOCX file.")


def _bounded_text(text: str) -> str:
    cleaned = (text or "").replace("\x00", "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="No readable text found in the document.")
    if len(cleaned) > MAX_EXTRACTED_CHARS:
        raise HTTPException(status_code=413, detail="Extracted document text exceeds the safe processing limit.")
    return cleaned


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import PyPDF2

    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise HTTPException(status_code=400, detail="Encrypted PDF files are not supported.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail="PDF has too many pages for safe processing.")
        parts = []
        size = 0
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                size += len(extracted)
                if size > MAX_EXTRACTED_CHARS:
                    raise HTTPException(status_code=413, detail="Extracted document text exceeds the safe processing limit.")
                parts.append(extracted)
        return _bounded_text("\n".join(parts))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to parse PDF safely.")


def extract_text_from_docx(file_bytes: bytes) -> str:
    import docx

    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        return _bounded_text("\n".join([paragraph.text for paragraph in doc.paragraphs]))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to parse DOCX safely.")


def extract_text_from_csv(file_bytes: bytes) -> str:
    try:
        text_data = file_bytes.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text_data))
        lines = []
        for index, row in enumerate(reader):
            if index >= 10000:
                raise HTTPException(status_code=413, detail="CSV contains too many rows for safe processing.")
            lines.append(" | ".join(row))
        return _bounded_text("\n".join(lines))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to parse CSV safely.")


def _source_block(source_id: int, text: str) -> str:
    return f"\n\n--- [VELOR SOURCE {source_id} BEGIN] ---\n{text}\n--- [VELOR SOURCE {source_id} END] ---\n"


def _remove_source_block(knowledge_base: str, source_id: int) -> str:
    pattern = re.compile(
        rf"\s*--- \[VELOR SOURCE {source_id} BEGIN\] ---.*?--- \[VELOR SOURCE {source_id} END\] ---\s*",
        re.DOTALL,
    )
    return pattern.sub("\n\n", knowledge_base or "").strip()


def _serialize_source(source: KnowledgeSource) -> dict:
    return {
        "id": source.id,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "status": source.status,
        "active": bool(source.active and not source.is_deleted),
        "extracted_char_count": source.extracted_char_count,
        "chunk_count": source.chunk_count,
        "last_processed": source.last_processed_at.isoformat() if source.last_processed_at else None,
        "last_synced": source.last_synced_at.isoformat() if source.last_synced_at else None,
        "error_category": source.error_category,
    }


@router.post("/upload")
async def upload_knowledge_file(file: UploadFile = File(...), current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    filename, extension = _safe_source_filename(file.filename)
    # Read one byte beyond the limit so oversized uploads are rejected without
    # buffering an arbitrary request body in memory.
    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.")
    _validate_upload_bytes(extension, file.content_type, file_bytes)

    if extension == ".pdf":
        text = extract_text_from_pdf(file_bytes)
    elif extension == ".docx":
        text = extract_text_from_docx(file_bytes)
    elif extension == ".csv":
        text = extract_text_from_csv(file_bytes)
    else:
        try:
            decoded = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Failed to parse TXT file. It must be UTF-8.")
        text = _bounded_text(decoded)

    company_id = current_user["company_id"]
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == company_id).first()
    if not knowledge:
        knowledge = CompanyKnowledge(company_id=company_id, knowledge_base="")
        db.add(knowledge)

    now = datetime.now(timezone.utc)
    source = KnowledgeSource(
        company_id=company_id,
        source_name=filename,
        source_type=extension.lstrip("."),
        mime_type=(file.content_type or "application/octet-stream")[:120],
        status="processed",
        extracted_text=text,
        extracted_char_count=len(text),
        chunk_count=max(1, math.ceil(len(text) / 300)),
        active=True,
        last_processed_at=now,
        last_synced_at=now,
    )
    db.add(source)

    try:
        db.flush()
        compiled = (knowledge.knowledge_base or "").rstrip() + _source_block(source.id, text)
        if len(compiled) > MAX_COMPILED_KNOWLEDGE_CHARS:
            raise HTTPException(status_code=413, detail="Combined active knowledge exceeds the safe processing limit.")
        knowledge.knowledge_base = compiled
        from services.workspace_suggestion_service import invalidate_company_suggestions
        invalidate_company_suggestions(db, company_id, "knowledge_changed")
        db.commit()
        db.refresh(source)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error while saving knowledge.")

    return {
        "success": True,
        "message": "File processed and added as an active knowledge source.",
        "extracted_length": len(text),
        "source": _serialize_source(source),
    }


@router.get("/sources")
def list_knowledge_sources(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(KnowledgeSource)
        .filter(KnowledgeSource.company_id == current_user["company_id"], KnowledgeSource.is_deleted == False)
        .order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.id.desc())
        .all()
    )
    return {"success": True, "sources": [_serialize_source(row) for row in rows]}


@router.patch("/sources/{source_id}")
def update_knowledge_source(
    source_id: int,
    data: KnowledgeSourceUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = db.query(KnowledgeSource).filter(
        KnowledgeSource.id == source_id,
        KnowledgeSource.company_id == current_user["company_id"],
        KnowledgeSource.is_deleted == False,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found.")
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == current_user["company_id"]).first()
    if not knowledge:
        raise HTTPException(status_code=409, detail="Knowledge storage is not initialized.")

    compiled = _remove_source_block(knowledge.knowledge_base or "", source.id)
    if data.active:
        compiled += _source_block(source.id, source.extracted_text)
        if len(compiled) > MAX_COMPILED_KNOWLEDGE_CHARS:
            raise HTTPException(status_code=413, detail="Combined active knowledge exceeds the safe processing limit.")
        source.status = "processed"
        source.last_processed_at = datetime.now(timezone.utc)
    else:
        source.status = "disabled"
    source.active = data.active
    source.last_synced_at = datetime.now(timezone.utc)
    knowledge.knowledge_base = compiled
    from services.workspace_suggestion_service import invalidate_company_suggestions
    invalidate_company_suggestions(db, current_user["company_id"], "knowledge_changed")
    db.commit()
    db.refresh(source)
    return {"success": True, "source": _serialize_source(source)}


@router.post("/sources/{source_id}/reprocess")
def reprocess_knowledge_source(source_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return update_knowledge_source(source_id, KnowledgeSourceUpdate(active=True), current_user, db)


@router.delete("/sources/{source_id}")
def delete_knowledge_source(source_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    source = db.query(KnowledgeSource).filter(
        KnowledgeSource.id == source_id,
        KnowledgeSource.company_id == current_user["company_id"],
        KnowledgeSource.is_deleted == False,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found.")
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == current_user["company_id"]).first()
    if knowledge:
        knowledge.knowledge_base = _remove_source_block(knowledge.knowledge_base or "", source.id)
    source.active = False
    source.status = "deleted"
    source.is_deleted = True
    source.deleted_at = datetime.now(timezone.utc)
    source.last_synced_at = datetime.now(timezone.utc)
    from services.workspace_suggestion_service import invalidate_company_suggestions
    invalidate_company_suggestions(db, current_user["company_id"], "knowledge_changed")
    db.commit()
    return {"success": True}
