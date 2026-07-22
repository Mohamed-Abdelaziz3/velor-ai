import hashlib
import hmac

import pytest
from fastapi import HTTPException

import routers.webhook as webhook


def test_meta_signature_validation_fails_closed_and_accepts_exact_hmac(monkeypatch):
    body = b'{"entry":[]}'
    monkeypatch.setattr(webhook, "META_APP_SECRET", "test-meta-secret")
    signature = "sha256=" + hmac.new(b"test-meta-secret", body, hashlib.sha256).hexdigest()

    webhook._validate_meta_signature(body, signature)
    with pytest.raises(HTTPException) as missing:
        webhook._validate_meta_signature(body, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as invalid:
        webhook._validate_meta_signature(body, "sha256=" + "0" * 64)
    assert invalid.value.status_code == 401


def test_meta_signature_requires_configured_secret(monkeypatch):
    monkeypatch.setattr(webhook, "META_APP_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        webhook._validate_meta_signature(b"{}", "sha256=anything")
    assert exc.value.status_code == 503
