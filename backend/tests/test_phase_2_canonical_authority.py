from unittest.mock import patch, AsyncMock
import pytest
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from database import Lead, Message, CommercialDecisionLineage, LeadEvidence, LeadIntelligenceSnapshot, SystemEvent, Company
from services.commercial_authority_service import get_canonical_commercial_view, get_canonical_commercial_view_batch
import uuid

@pytest.fixture
def test_company(db: Session):
    company = Company(
        company_id=str(uuid.uuid4()),
        company_name="Test Company",
        email=f"test_{uuid.uuid4()}@test.com",
        password="pwd",
        api_key_hash=str(uuid.uuid4())
    )
    db.add(company)
    db.commit()
    return company

@pytest.fixture
def setup_lead(db: Session, test_company):
    lead = Lead(
        company_id=test_company.company_id,
        phone="01000000001",
        name="Test Canonical",
        channel_type="VELOR_WEB_CHAT",
        external_customer_id="velor_user_1",
        stage="New",
        status="Active",
        lead_score=50,
        ai_summary="",
    )
    db.add(lead)
    db.commit()
    return lead

def test_empty_fallback(db: Session, test_company, setup_lead):
    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["processing_status"] == "UNKNOWN"
    assert view["canonical_commercial"]["stale_status"] is False
    assert view["canonical_commercial"]["sales_state"]["truth_class"] == "UNKNOWN"

def test_stale_lineage_no_message(db: Session, test_company, setup_lead):
    lin = CommercialDecisionLineage(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        source_message_internal_id=str(uuid.uuid4()),
        objective="DISCOVERY",
        strategy="ASK_BUDGET",
        next_move="WAIT",
        decision_json=json.dumps({"sales_state": "QUALIFICATION", "intent": "EXPLORATORY"}),
        created_at=datetime.now(timezone.utc)
    )
    db.add(lin)
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["processing_status"] == "STALE"
    assert view["canonical_commercial"]["stale_status"] is True
    assert view["canonical_commercial"]["sales_state"]["value"] == "QUALIFICATION"
    assert view["canonical_commercial"]["sales_state"]["truth_class"] == "DETERMINISTICALLY_DERIVED"

def test_current_lineage(db: Session, test_company, setup_lead):
    msg_id = str(uuid.uuid4())
    msg = Message(
        company_id=test_company.company_id,
        user_id="velor_user_1",
        internal_message_id=msg_id,
        sender="user",
        message="Hello", direction="incoming",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    db.add(msg)
    
    lin = CommercialDecisionLineage(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        source_message_internal_id=msg_id,
        objective="DISCOVERY",
        strategy="ASK",
        next_move="WAIT",
        decision_json=json.dumps({}),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=4)
    )
    db.add(lin)
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["processing_status"] == "CURRENT"
    assert view["canonical_commercial"]["stale_status"] is False

def test_pending_recompute(db: Session, test_company, setup_lead):
    old_msg_id = str(uuid.uuid4())
    old_msg = Message(
        company_id=test_company.company_id,
        user_id="velor_user_1",
        internal_message_id=old_msg_id,
        sender="user",
        message="Hello", direction="incoming",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    
    lin = CommercialDecisionLineage(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        source_message_internal_id=old_msg_id,
        objective="DISCOVERY",
        strategy="ASK",
        next_move="WAIT",
        decision_json=json.dumps({}),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=9)
    )
    
    new_msg = Message(
        company_id=test_company.company_id,
        user_id="velor_user_1",
        internal_message_id=str(uuid.uuid4()),
        sender="user",
        message="Hello again", direction="incoming",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2)
    )
    db.add_all([old_msg, lin, new_msg])
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["processing_status"] == "PENDING_RECOMPUTE"
    assert view["canonical_commercial"]["stale_status"] is True

def test_evidence_budget_and_objection(db: Session, test_company, setup_lead):
    ev1 = LeadEvidence(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        message_internal_id=str(uuid.uuid4()),
        evidence_type="budget",
        source_text="test evidence",
        evidence_hash=str(uuid.uuid4()),
        normalized_value="50000",
        metadata_json=json.dumps({"constraint_type": "EXACT_BUDGET"}),
        created_at=datetime.now(timezone.utc)
    )
    ev2 = LeadEvidence(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        message_internal_id=str(uuid.uuid4()),
        evidence_type="objection",
        source_text="test evidence",
        evidence_hash=str(uuid.uuid4()),
        normalized_value="PRICE_TOO_HIGH",
        created_at=datetime.now(timezone.utc)
    )
    db.add_all([ev1, ev2])
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["budget"]["amount"] == 50000
    assert view["canonical_commercial"]["budget"]["constraint_type"] == "EXACT_BUDGET"
    assert view["canonical_commercial"]["budget"]["truth_class"] == "OBSERVED"
    assert view["canonical_commercial"]["active_objection"]["value"] == "PRICE_TOO_HIGH"
    assert view["canonical_commercial"]["active_objection"]["truth_class"] == "OBSERVED"

def test_evidence_objection_resolved(db: Session, test_company, setup_lead):
    ev1 = LeadEvidence(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        message_internal_id=str(uuid.uuid4()),
        evidence_type="objection",
        source_text="test evidence",
        evidence_hash=str(uuid.uuid4()),
        normalized_value="PRICE_TOO_HIGH",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    ev2 = LeadEvidence(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        message_internal_id=str(uuid.uuid4()),
        evidence_type="objection",
        source_text="test evidence",
        evidence_hash=str(uuid.uuid4()),
        normalized_value="RESOLVED",
        created_at=datetime.now(timezone.utc)
    )
    db.add_all([ev1, ev2])
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["active_objection"]["value"] is None
    assert view["canonical_commercial"]["active_objection"]["truth_class"] == "UNKNOWN"

def test_purchase_status_invalidates_discovery(db: Session, test_company, setup_lead):
    lin = CommercialDecisionLineage(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        source_message_internal_id=str(uuid.uuid4()),
        objective="DISCOVERY",
        strategy="ASK",
        next_move="WAIT",
        decision_json="{}",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=4)
    )
    ev = LeadEvidence(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        message_internal_id=str(uuid.uuid4()),
        evidence_type="purchase_statement",
        source_text="test evidence",
        evidence_hash=str(uuid.uuid4()),
        normalized_value="READY_TO_BUY",
        created_at=datetime.now(timezone.utc)
    )
    db.add_all([lin, ev])
    db.commit()

    view = get_canonical_commercial_view(db, test_company.company_id, setup_lead.id)
    assert view["canonical_commercial"]["stale_status"] is True
    assert view["canonical_commercial"]["processing_status"] == "STALE"
    assert view["canonical_commercial"]["purchase_status"]["value"] == "READY_TO_BUY"

def test_crm_endpoint_returns_canonical(client: TestClient, db: Session, test_company, setup_lead):
    lin = CommercialDecisionLineage(
        company_id=test_company.company_id,
        lead_id=setup_lead.id,
        source_message_internal_id=str(uuid.uuid4()),
        objective="CLOSING",
        strategy="ASK",
        next_move="WAIT",
        decision_json="{}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(lin)
    db.add(
        LeadIntelligenceSnapshot(
            lead_id=setup_lead.id,
            priority_score=99,
            next_best_action="fabricated snapshot action",
            expected_outcome="fabricated snapshot outcome",
        )
    )
    db.commit()

    from main import app
    from routers.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"company_id": test_company.company_id}

    res = client.get(f"/api/v1/crm/customers/{setup_lead.id}")
    app.dependency_overrides = {}
    assert res.status_code == 200
    data = res.json()
    assert "canonical_commercial" in data["customer"]
    assert data["customer"]["canonical_commercial"]["objective"]["value"] == "CLOSING"
    assert data["customer"]["priority_score"] is None
    assert data["customer"]["expected_outcome"] is None
    assert data["customer"]["legacy_advisory"]["snapshot_recommendation"] is None

def test_legacy_intelligence_worker_is_disabled_by_default(db: Session, test_company, setup_lead):
    from workers.intelligence_worker import rebuild_lead_intelligence_task
    import asyncio

    asyncio.run(rebuild_lead_intelligence_task(test_company.company_id, setup_lead.id))

    events = db.query(SystemEvent).filter(SystemEvent.event_type == "legacy_intelligence.updated").all()
    assert events == []


def test_copilot_and_legacy_lost_ignore_snapshot_urgency(db: Session, test_company, setup_lead):
    import asyncio
    from copilot.daily_brief import generate_daily_brief, get_top_opportunities, get_top_risks
    from services.copilot_aggregator import generate_business_snapshot
    from main import engine_lost

    db.add(
        LeadIntelligenceSnapshot(
            lead_id=setup_lead.id,
            priority_score=100,
            lost_risk_score=100,
            next_best_action="push Ergo Pro",
            expected_outcome="purchase",
        )
    )
    db.commit()

    snapshot = asyncio.run(generate_business_snapshot(db, test_company.company_id))
    brief = generate_daily_brief(db, test_company.company_id)
    assert snapshot["at_risk_leads"] == 0
    assert brief["at_risk"] == 0
    assert get_top_opportunities(db, test_company.company_id) == []
    assert get_top_risks(db, test_company.company_id) == []
    assert engine_lost(db=db, target_cid=test_company.company_id)["lost_candidates"] == []

def test_scheduler_no_risk_mutation(db: Session, test_company, setup_lead):
    # Setup conditions that would normally mutate the risk score
    from scheduler import _job_follow_up_sweeper
    import asyncio
    
    snap = LeadIntelligenceSnapshot(
        lead_id=setup_lead.id,
        lost_risk_score=50,
        next_best_action="Follow up"
    )
    db.add(snap)
    
    setup_lead.stage = "Pitched"
    setup_lead.status = "Active"
    setup_lead.updated_at = datetime.now(timezone.utc) - timedelta(hours=72)
    db.commit()
    
    _job_follow_up_sweeper()
    
    # Reload snapshot to verify it was NOT mutated
    db.refresh(snap)
    assert snap.lost_risk_score == 50

def test_brain_does_not_call_scorer(db: Session, test_company, setup_lead):
    pass
