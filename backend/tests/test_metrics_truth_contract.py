from datetime import datetime, timezone

from database import Company, Lead, Message, UsageStats
from main import _iso_utc
from services.sse_metrics import compute_and_cache_metrics, invalidate_metrics_cache


def test_dashboard_counts_canonical_rows_not_stale_usage_counters(db):
    company = Company(
        company_id="metrics_truth",
        company_name="Metrics Truth",
        email="metrics-truth@example.com",
        password="not-used",
        api_key_hash="f" * 64,
    )
    db.add(company)
    db.flush()
    db.add(
        Lead(
            company_id=company.company_id,
            name="Web visitor",
            external_customer_id="visitor_metrics_truth",
            channel_type="VELOR_WEB_CHAT",
            stage="New",
            is_test=False,
        )
    )
    db.add_all(
        [
            Message(
                company_id=company.company_id,
                user_id="visitor_metrics_truth",
                sender="user",
                direction="incoming",
                message="Hello",
                internal_message_id="metrics-incoming",
                created_at=datetime.now(timezone.utc),
            ),
            Message(
                company_id=company.company_id,
                user_id="visitor_metrics_truth",
                sender="assistant",
                direction="outgoing",
                message="Hi",
                internal_message_id="metrics-outgoing",
                created_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db.add(
        Lead(
            company_id=company.company_id,
            name="Synthetic fixture",
            external_customer_id="visitor_synthetic_fixture",
            channel_type="VELOR_WEB_CHAT",
            stage="New",
            is_test=True,
        )
    )
    db.add(
        Message(
            company_id=company.company_id,
            user_id="visitor_synthetic_fixture",
            sender="assistant",
            direction="outgoing",
            message="Synthetic reply",
            internal_message_id="metrics-synthetic",
            created_at=datetime.now(timezone.utc),
        )
    )
    db.add(UsageStats(company_id=company.company_id, leads_count=0, messages_count=0))
    db.commit()

    invalidate_metrics_cache(company.company_id)
    metrics = compute_and_cache_metrics(db, company.company_id)

    assert metrics["total_leads"] == 1
    assert metrics["total_conversations"] == 2
    assert metrics["won_deals_today"] is None
    assert metrics["metrics_meta"]["total_conversations"]["unit"] == "messages"
    assert metrics["metrics_meta"]["as_of"].endswith("Z")


def test_api_timestamps_are_explicit_utc_even_when_sqlite_returns_naive_values():
    assert _iso_utc(datetime(2026, 7, 15, 9, 30)) == "2026-07-15T09:30:00Z"
    assert _iso_utc(datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)) == "2026-07-15T09:30:00Z"


def test_public_demo_sessions_are_marked_test_data(client, db):
    company = Company(
        company_id="velor_demo_truth_contract",
        company_name="Synthetic demo",
        email="truth-contract@demo.local",
        password="not-used",
        api_key_hash="e" * 64,
        is_web_chat_enabled=True,
        public_chat_slug="truth-contract-demo",
    )
    db.add(company)
    db.commit()

    response = client.post("/api/public/companies/truth-contract-demo/session")
    assert response.status_code == 200
    visitor_id = response.json()["visitor_id"]
    lead = db.query(Lead).filter(Lead.external_customer_id == visitor_id).one()
    assert lead.is_test is True
