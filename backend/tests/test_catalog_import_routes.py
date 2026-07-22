import io
import json
import zipfile

from jose import jwt

from database import Company, CompanyKnowledge, hash_api_key


def _token(company_id):
    return jwt.encode(
        {"company_id": company_id, "role": "tenant", "token_type": "access"},
        "super-secret-test-key-32-chars-long",
        algorithm="HS256",
    )


def _seed(db, company_id):
    db.add(Company(
        company_id=company_id,
        company_name=company_id,
        email=f"{company_id}@example.com",
        password="hashed",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
    ))
    db.add(CompanyKnowledge(company_id=company_id, products_data="[]"))
    db.commit()


def test_catalog_csv_preview_commit_list_and_tenant_scope(client, db):
    _seed(db, "catalog_a")
    _seed(db, "catalog_b")
    content = "name,category,price,currency,description\nErgo One,chairs,6900,EGP,Mesh chair\n".encode()

    preview = client.post(
        "/api/v1/catalog/import",
        files={"file": ("catalog.csv", content, "text/csv")},
        cookies={"access_token": _token("catalog_a")},
    )
    assert preview.status_code == 200
    assert preview.json()["committed"] is False
    assert preview.json()["preview"]["stats"]["accepted_records"] == 1
    assert db.query(CompanyKnowledge).filter(CompanyKnowledge.company_id == "catalog_a").one().products_data == "[]"

    committed = client.post(
        "/api/v1/catalog/import?commit=true",
        files={"file": ("catalog.csv", content, "text/csv")},
        cookies={"access_token": _token("catalog_a")},
    )
    assert committed.status_code == 200
    assert committed.json()["committed"] is True

    listed = client.get("/api/v1/catalog?category=chairs", cookies={"access_token": _token("catalog_a")})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["records"][0]["price"] == 6900.0
    other = client.get("/api/v1/catalog", cookies={"access_token": _token("catalog_b")})
    assert other.json()["total"] == 0


def test_catalog_import_rejects_binary_csv_and_unsafe_xlsx(client, db):
    _seed(db, "catalog_security")
    binary = client.post(
        "/api/v1/catalog/import",
        files={"file": ("catalog.csv", b"name\x00price", "text/csv")},
        cookies={"access_token": _token("catalog_security")},
    )
    assert binary.status_code == 400

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")
        archive.writestr("xl/vbaProject.bin", b"macro")
    unsafe = client.post(
        "/api/v1/catalog/import",
        files={"file": ("catalog.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        cookies={"access_token": _token("catalog_security")},
    )
    assert unsafe.status_code == 400
