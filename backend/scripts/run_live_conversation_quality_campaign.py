"""Run a real-provider, synthetic Egyptian-Arabic multi-turn launch gate.

The script uses an isolated temporary SQLite database and prints only aggregate
quality metadata. It never prints prompts, customer text, provider output, or
credentials.
"""

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, Company, CompanyKnowledge, Lead, Message, hash_api_key
from services.public_chat_turn_service import persist_v2_public_turn_atomic
from services.velor_chat_v2 import (
    check_provider_readiness,
    build_response_context,
    get_v2_ai_response,
    validate_writer_style,
)


CAMPAIGN_TURNS = [
    "السلام عليكم",
    "بدور على كرسي للشغل حوالي 8 ساعات كل يوم",
    "ميزانيتي آخرها 7000 جنيه",
    "إيه الأنسب من الموجود وليه؟",
    "السعر غالي شوية بصراحة",
    "ما تتصلش بيا، خلينا نكمل هنا",
    "طب الضمان كام؟",
    "والتوصيل بيكون إزاي؟",
    "تمام، لو Arvena Ergo One مناسب هبدأ الطلب",
]


def _seed(session):
    company_id = f"quality_{uuid.uuid4().hex[:10]}"
    company = Company(
        company_id=company_id,
        company_name="متجر الاختبار المعزول",
        email=f"{company_id}@example.invalid",
        password="not-used",
        api_key_hash=hash_api_key(f"{company_id}-key"),
        plan="PRO",
        bot_auto_reply_enabled=True,
    )
    knowledge = CompanyKnowledge(
        company_id=company_id,
        system_prompt=(
            "اتكلم بهدوء وبطريقة عملية، جاوب مباشرة، وما تضغطش على العميل."
        ),
        tone="Warm practical Egyptian Arabic",
        products_data=json.dumps(
            [
                {
                    "name": "Arvena Ergo One",
                    "category": "كراسي مكتبية",
                    "price": 6900,
                    "currency": "EGP",
                    "sku": "AE-ONE",
                    "description": "كرسي مكتبي بدعم للظهر وظهر شبكي",
                },
                {
                    "name": "Arvena Ergo Pro",
                    "category": "كراسي مكتبية",
                    "price": 8900,
                    "currency": "EGP",
                    "sku": "AE-PRO",
                    "description": "كرسي مكتبي بمساند قابلة للتعديل ومسند رأس",
                },
            ],
            ensure_ascii=False,
        ),
        knowledge_base=(
            "سياسة الاسترجاع المعتمدة خلال 14 يوماً من الاستلام.\n"
            "الضمان المعتمد سنة ضد عيوب الصناعة.\n"
            "التوصيل داخل القاهرة خلال 2 إلى 4 أيام عمل ورسومه 80 جنيه.\n"
            "طريقة الدفع المتاحة هي الدفع عند الاستلام."
        ),
    )
    lead = Lead(
        company_id=company_id,
        name="عميل اختبار",
        phone="1009998888",
        whatsapp_number="1009998888",
        whatsapp_jid="201009998888@s.whatsapp.net",
        channel_type="WHATSAPP_QR",
        external_customer_id="201009998888@s.whatsapp.net",
        is_paused=False,
        status="new",
    )
    session.add_all([company, knowledge, lead])
    session.commit()
    return company_id, lead.id


async def _run() -> int:
    readiness = check_provider_readiness()
    if not readiness["configured"]:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "runtime_quality_certified": False,
                    "reason": "provider_unconfigured",
                    "provider": readiness["provider"],
                    "model": readiness["model_name"],
                }
            )
        )
        return 2

    temp_path = Path(tempfile.gettempdir()) / f"velor_quality_{uuid.uuid4().hex}.db"
    engine = create_engine(
        f"sqlite:///{temp_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    results = []
    try:
        with Session() as session:
            company_id, lead_id = _seed(session)
            for index, customer_text in enumerate(CAMPAIGN_TURNS, start=1):
                company = session.query(Company).filter(
                    Company.company_id == company_id
                ).one()
                lead = session.query(Lead).filter(Lead.id == lead_id).one()
                inbound = Message(
                    internal_message_id=str(uuid.uuid4()),
                    public_message_id=f"pub-{uuid.uuid4().hex}",
                    wa_message_id=f"quality:{index}:{uuid.uuid4().hex}",
                    company_id=company_id,
                    user_id=lead.whatsapp_jid,
                    sender="user",
                    direction="incoming",
                    message=customer_text,
                    delivery_status="received",
                    processing_status="processing",
                    processing_attempts=1,
                )
                session.add(inbound)
                session.commit()
                session.refresh(inbound)

                response = await get_v2_ai_response(
                    db=session,
                    source_message=inbound,
                    company=company,
                    lead=lead,
                    channel_type="WHATSAPP_QR",
                    source_route="/quality-campaign",
                )
                trace = response["trace"]
                style_violations = validate_writer_style(
                    response["answer_text"],
                    build_response_context(
                        session,
                        inbound,
                        company,
                        lead,
                        channel_type_override="WHATSAPP_QR",
                        source_route_override="/quality-campaign",
                    ),
                )
                persisted = persist_v2_public_turn_atomic(
                    db=session,
                    company_id=company_id,
                    lead_id=lead_id,
                    user_id=lead.whatsapp_jid,
                    customer_text=customer_text,
                    assistant_text=response["answer_text"],
                    inbound_internal_id=inbound.internal_message_id,
                    processing_claim_attempt=inbound.processing_attempts,
                    lead_update=trace.get("lead_to_save"),
                    decision=trace.get("action_decision"),
                    sales_snapshot=trace.get("sales_snapshot"),
                    objection_snapshot=trace.get("objection_snapshot"),
                    recommendation_decision=trace.get("recommendation_decision"),
                    response_envelope=response.get("response_envelope"),
                    conversation_action=trace.get("conversation_action"),
                    trace=trace,
                    channel_type="WHATSAPP_QR",
                    outbound_delivery_status="sent",
                    telemetry_source="quality_campaign",
                )
                results.append(
                    {
                        "turn": index,
                        "response_path": response["response_path"],
                        "verifier": trace.get("verifier_result"),
                        "fallback_reason": trace.get("fallback_reason"),
                        "style_violations": style_violations,
                        "model_calls": trace.get("model_call_count"),
                        "latency_ms": trace.get("latency_ms"),
                        "persisted": bool(persisted),
                    }
                )
    finally:
        engine.dispose()
        try:
            temp_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    failed_turns = [
        result
        for result in results
        if (
            result["response_path"] != "MODEL"
            or result["verifier"] != "PASS"
            or result["style_violations"]
            or not result["persisted"]
        )
    ]
    summary = {
        "status": "passed" if not failed_turns else "failed",
        "runtime_quality_certified": not failed_turns,
        "provider": readiness["provider"],
        "model": readiness["model_name"],
        "turns_run": len(results),
        "model_turns": sum(
            result["response_path"] == "MODEL" for result in results
        ),
        "fallback_turns": sum(
            result["response_path"] != "MODEL" for result in results
        ),
        "failed_turns": [result["turn"] for result in failed_turns],
        "failure_codes": sorted(
            {
                code
                for result in failed_turns
                for code in (
                    [result["fallback_reason"]]
                    + result["style_violations"]
                    + (
                        [f"VERIFIER_{result['verifier']}"]
                        if result["verifier"] != "PASS"
                        else []
                    )
                )
                if code
            }
        ),
        "max_latency_ms": max(
            (result["latency_ms"] or 0 for result in results),
            default=0,
        ),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not failed_turns else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
