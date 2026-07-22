import io
import zipfile

import pytest
from fastapi import HTTPException
from jose import jwt

from database import Company, CompanyKnowledge, KnowledgeSource, hash_api_key
from routers.knowledge import _safe_source_filename, _validate_docx_archive


def _token(company_id: str) -> str:
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed(db, company_id: str) -> None:
    db.add(
        Company(
            company_id=company_id,
            company_name=company_id,
            email=f"{company_id}@example.com",
            password="hashed",
            api_key_hash=hash_api_key(f"{company_id}-key"),
            plan="PRO",
        )
    )
    db.add(CompanyKnowledge(company_id=company_id, knowledge_base="Manual policy"))
    db.commit()


def test_filename_and_magic_validation_reject_spoofed_uploads(client, db):
    _seed(db, "knowledge_spoof")

    with pytest.raises(HTTPException):
        _safe_source_filename("../unsafe.txt")

    response = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("policy.pdf", b"this is not a PDF", "application/pdf")},
        cookies={"access_token": _token("knowledge_spoof")},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Invalid PDF file."
    assert db.query(KnowledgeSource).count() == 0


def test_docx_macro_or_executable_payload_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
        archive.writestr("word/vbaProject.bin", b"macro")

    with pytest.raises(HTTPException) as exc:
        _validate_docx_archive(buffer.getvalue())
    assert exc.value.status_code == 400
    assert "Unsafe content" in exc.value.detail


def test_source_lifecycle_is_tenant_scoped_and_updates_retrievable_text(client, db):
    _seed(db, "knowledge_a")
    _seed(db, "knowledge_b")
    upload = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("returns.txt", "الاسترجاع خلال 14 يوم".encode("utf-8"), "text/plain")},
        cookies={"access_token": _token("knowledge_a")},
    )
    assert upload.status_code == 200
    source_id = upload.json()["source"]["id"]
    assert upload.json()["source"]["status"] == "processed"

    listed = client.get(
        "/api/v1/knowledge/sources",
        cookies={"access_token": _token("knowledge_a")},
    )
    assert [row["id"] for row in listed.json()["sources"]] == [source_id]

    cross_tenant = client.patch(
        f"/api/v1/knowledge/sources/{source_id}",
        json={"active": False},
        cookies={"access_token": _token("knowledge_b")},
    )
    assert cross_tenant.status_code == 404

    disabled = client.patch(
        f"/api/v1/knowledge/sources/{source_id}",
        json={"active": False},
        cookies={"access_token": _token("knowledge_a")},
    )
    assert disabled.status_code == 200
    assert disabled.json()["source"]["active"] is False
    db.expire_all()
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == "knowledge_a").one()
    assert "الاسترجاع خلال 14 يوم" not in knowledge.knowledge_base
    assert "Manual policy" in knowledge.knowledge_base

    reprocessed = client.post(
        f"/api/v1/knowledge/sources/{source_id}/reprocess",
        cookies={"access_token": _token("knowledge_a")},
    )
    assert reprocessed.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == "knowledge_a").one()
    assert "الاسترجاع خلال 14 يوم" in knowledge.knowledge_base

    deleted = client.delete(
        f"/api/v1/knowledge/sources/{source_id}",
        cookies={"access_token": _token("knowledge_a")},
    )
    assert deleted.status_code == 200
    knowledge = db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == "knowledge_a").one()
    assert "الاسترجاع خلال 14 يوم" not in knowledge.knowledge_base


def test_binary_text_and_oversized_body_are_rejected_before_persistence(client, db, monkeypatch):
    _seed(db, "knowledge_limits")
    binary = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("binary.txt", b"safe\x00unsafe", "text/plain")},
        cookies={"access_token": _token("knowledge_limits")},
    )
    assert binary.status_code == 400

    monkeypatch.setattr("routers.knowledge.MAX_UPLOAD_BYTES", 4)
    oversized = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("large.txt", b"12345", "text/plain")},
        cookies={"access_token": _token("knowledge_limits")},
    )
    assert oversized.status_code == 413
    assert db.query(KnowledgeSource).filter(KnowledgeSource.company_id == "knowledge_limits").count() == 0
