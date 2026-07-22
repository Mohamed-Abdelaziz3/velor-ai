import json
import pytest
from sqlalchemy.orm import Session
from unittest.mock import patch, MagicMock
import httpx

from database import Lead, Company, CompanyKnowledge, Message, hash_api_key
from utils import repair_mojibake
from copilot.daily_brief import generate_daily_brief, get_whatsapp_status
from services.copilot_aggregator import generate_business_snapshot

def _seed_company(db: Session, company_id: str):
    db.query(Company).filter(Company.company_id == company_id).delete()
    db.commit()
    co = Company(
        company_id=company_id,
        company_name="Test Truth Co",
        email=f"{company_id}@test.com",
        password="hash",
        api_key_hash=hash_api_key(f"{company_id}-key")
    )
    db.add(co)
    db.commit()
    return co

def test_repair_mojibake_preserves_valid_arabic_and_english():
    # 1. Valid Arabic unchanged
    assert repair_mojibake("عميل محتمل") == "عميل محتمل"
    # 2. Valid English unchanged
    assert repair_mojibake("Customer name") == "Customer name"
    # 3. Mixed Arabic/English unchanged
    assert repair_mojibake("عميل and English") == "عميل and English"
    # 4. Already-repaired Arabic not double-transformed
    assert repair_mojibake(repair_mojibake("عميل")) == "عميل"
    # 5. Reversible legacy corruption repaired
    orig = "عميل محتمل"
    mojibake = orig.encode("utf-8").decode("cp1252")
    assert repair_mojibake(mojibake) == orig
    # 6. Ambiguous text unchanged
    ambiguous = "Ø¹\ud800Ù"
    assert repair_mojibake(ambiguous) == ambiguous

def test_clean_round_trip(db: Session):
    # 7. Current clean write/read round trip remains clean and does not corrupt Arabic
    company_id = "test_truth_co"
    _seed_company(db, company_id)
    new_lead = Lead(
        company_id=company_id,
        name="عميل جديد نظيف",
        phone="201002223334",
        whatsapp_number="201002223334",
        ai_summary="ملخص نظيف للمحادثة باللغة العربية",
        stage="New"
    )
    db.add(new_lead)
    db.commit()
    
    db.refresh(new_lead)
    assert new_lead.name == "عميل جديد نظيف"
    assert new_lead.ai_summary == "ملخص نظيف للمحادثة باللغة العربية"
    
    db.delete(new_lead)
    db.commit()

def test_whatsapp_status_mapping():
    # Test mapping logic for CONNECTED, DISCONNECTED, and UNKNOWN
    with patch("httpx.Client.get") as mock_get:
        # Connected Case
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "status": "connected"}
        mock_get.return_value = mock_resp
        assert get_whatsapp_status("test_co") == "CONNECTED"

        # Disconnected Case
        mock_resp.json.return_value = {"success": True, "status": "disconnected"}
        assert get_whatsapp_status("test_co") == "DISCONNECTED"

        # Stale Case (Mapped to DISCONNECTED)
        mock_resp.json.return_value = {"success": True, "status": "stale"}
        assert get_whatsapp_status("test_co") == "DISCONNECTED"

        # UNKNOWN Case (HTTP status 500)
        mock_resp.status_code = 500
        mock_resp.json.return_value = {}
        assert get_whatsapp_status("test_co") == "UNKNOWN"

        # UNKNOWN Case (Exception/timeout)
        mock_get.side_effect = httpx.ConnectTimeout("Timeout")
        assert get_whatsapp_status("test_co") == "UNKNOWN"

@pytest.mark.asyncio
async def test_unsupported_financial_metrics_hidden_and_not_zero(db: Session):
    company_id = "test_truth_co"
    _seed_company(db, company_id)
    snap = await generate_business_snapshot(db, company_id)
    assert snap.get("revenue") is None
    brief = generate_daily_brief(db, company_id)
    assert brief.get("revenue_at_risk") is None

def test_fake_confidence_score_absent(db: Session):
    company_id = "test_truth_co"
    _seed_company(db, company_id)
    brief = generate_daily_brief(db, company_id)
    assert brief.get("confidence_score") is None

def test_demo_mock_isolation_boundaries(db: Session):
    # 8. Explicit test/demo leads excluded; legitimate production leads preserved
    company_id = "test_truth_co"
    _seed_company(db, company_id)
    
    # Clean up any existing leads
    db.query(Lead).filter(Lead.company_id == company_id).delete()
    db.commit()

    # Legit production lead containing "Sprint" or "Test" or "Demo" in name
    legit_lead = Lead(
        company_id=company_id,
        name="Legit Sprint and Test Demo Lead",
        phone="10001",
        whatsapp_number="10001",
        is_test=False,
        stage="New"
    )
    # Explicit test lead
    test_lead = Lead(
        company_id=company_id,
        name="Explicit Test Lead",
        phone="10002",
        whatsapp_number="10002",
        is_test=True,
        stage="New"
    )
    db.add(legit_lead)
    db.add(test_lead)
    db.commit()

    # Get active leads filter
    from database import get_live_leads_filter
    live_leads = db.query(Lead).filter(Lead.company_id == company_id, get_live_leads_filter(Lead)).all()
    
    assert len(live_leads) == 1
    assert live_leads[0].phone == "10001"
    
    db.delete(legit_lead)
    db.delete(test_lead)
    db.commit()

def test_four_semantic_empty_states(db: Session):
    company_id = "test_truth_co"
    _seed_company(db, company_id)
    
    # Clean up leads
    db.query(Lead).filter(Lead.company_id == company_id).delete()
    db.commit()

    # State A: Channel Disconnected
    with patch("copilot.daily_brief.get_whatsapp_status", return_value="DISCONNECTED"):
        brief = generate_daily_brief(db, company_id)
        assert brief["velor_narrative"]["headline"] == "اربط قناة لبدء استقبال المحادثات"
        assert "يرجى ربط قناة واتساب" in brief["velor_narrative"]["context"]

    # State B: Channel Connected + 0 leads
    with patch("copilot.daily_brief.get_whatsapp_status", return_value="CONNECTED"):
        brief = generate_daily_brief(db, company_id)
        assert brief["velor_narrative"]["headline"] == "تم ربط القناة بنجاح"
        assert "المنصة متصلة بـ WhatsApp" in brief["velor_narrative"]["context"]

    # Failure State: Channel Status UNKNOWN
    with patch("copilot.daily_brief.get_whatsapp_status", return_value="UNKNOWN"):
        brief = generate_daily_brief(db, company_id)
        assert brief["velor_narrative"]["headline"] == "تعذر التحقق من حالة القناة حالياً"
        assert "يرجى التحقق من اتصال الخادم" in brief["velor_narrative"]["context"]

    # State D: Conversations exist + 0 recommended actions but no analysis signals
    lead = Lead(
        company_id=company_id,
        name="Legit Customer",
        phone="10003",
        whatsapp_number="10003",
        is_test=False,
        stage="New",
        ai_summary=None
    )
    db.add(lead)
    db.commit()

    with patch("copilot.daily_brief.get_whatsapp_status", return_value="CONNECTED"):
        brief = generate_daily_brief(db, company_id)
        assert brief["velor_narrative"]["headline"] == "لا توجد بيانات كافية"
        assert "البيانات المتاحة غير كافية" in brief["velor_narrative"]["context"]

    # State C: Conversations exist + 0 recommended actions + analysis signals present (Truthful state)
    lead.ai_summary = "ملخص المحادثة"
    db.commit()

    with patch("copilot.daily_brief.get_whatsapp_status", return_value="CONNECTED"):
        brief = generate_daily_brief(db, company_id)
        assert brief["velor_narrative"]["headline"] == "تمت مراجعة 1 محادثات."
        assert brief["velor_narrative"]["context"] == "لا توجد إجراءات عاجلة مقترحة حالياً."

    db.delete(lead)
    db.commit()
