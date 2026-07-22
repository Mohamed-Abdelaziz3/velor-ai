import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncio
import uuid
from fastapi.testclient import TestClient
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.orm import Session
from database import SessionLocal, Lead, Message, CommercialDecisionLineage, LeadEvidence, CommercialEvent
from main import app

def run_scenario(client, db, scenario_name, visitor_id, messages):
    print(f"\n{'='*50}\nRunning {scenario_name}\n{'='*50}")
    
    resp = client.post("/api/public/companies/arvena-demo/session", json={"visitor_id": visitor_id, "source_channel": "website"})
    assert resp.status_code == 200, resp.text
    resp_json = resp.json()
    token = resp_json.get("token") or resp_json.get("data", {}).get("session_token")
    if not token:
        print("Failed to get session token!")
        return
        
    headers = {"Authorization": f"Bearer {token}"}
    actual_visitor_id = resp_json.get("visitor_id") or visitor_id
    
    for i, text in enumerate(messages):
        print(f"\n[Turn {i+1}] Customer: {text}")
        msg_resp = client.post("/api/public/chat", json={"message": text, "client_message_id": f"{actual_visitor_id}_msg_{i}"}, headers=headers)
        if msg_resp.status_code != 200:
            print(f"Error: {msg_resp.text}")
            continue
        data = msg_resp.json()
        print(f"Assistant: {data.get('data', {}).get('reply') or data.get('reply')}")

    lead = db.query(Lead).filter(Lead.external_customer_id == actual_visitor_id).first()
    if not lead:
        print("Lead not found in DB!")
        return

    print(f"\n--- DB State for {scenario_name} (Lead {lead.id}) ---")
    msgs = db.query(Message).filter(Message.user_id == actual_visitor_id).order_by(Message.id).all()
    print(f"Messages: {len(msgs)}")
    for m in msgs[-3:]:
        print(f"  {m.sender}: {m.message}")
        
    lineage = db.query(CommercialDecisionLineage).filter(CommercialDecisionLineage.lead_id == lead.id).order_by(CommercialDecisionLineage.id).all()
    print(f"Lineage Rows: {len(lineage)}")
    for l in lineage:
        print(f"  id={l.id} obj={l.objective} strat={l.strategy} move={l.next_move}")
        
    events = db.query(CommercialEvent).filter(CommercialEvent.lead_id == lead.id).all()
    print(f"Commercial Events: {len(events)}")
    for e in events:
        print(f"  {e.event_type} (prod={e.product_ref} stage={e.stage})")

    from services.commercial_authority_service import get_canonical_commercial_view
    state = get_canonical_commercial_view(db, "velor_demo_arvena", lead.id)
    cc = state.get("canonical_commercial", {})
    print("\nCanonical Commercial State:")
    print(f"  Sales State: {cc.get('sales_state', {}).get('value')}")
    print(f"  Budget: {cc.get('budget', {}).get('amount')}")
    print(f"  Primary Objection: {cc.get('active_objection', {}).get('value')}")
    print(f"  Purchase Status: {cc.get('purchase_status', {}).get('value')}")

def main():
    db = SessionLocal()
    client = TestClient(app)
    
    run_scenario(client, db, "Scenario E", "visitor_E", [
        "عايز كرسي كويس للشغل",
        "إيه الفرق بين Ergo One وErgo Pro؟",
        "10900 غالي جدًا",
        "أنا آخري 7000"
    ])
    
    run_scenario(client, db, "Scenario F", "visitor_F", [
        "تمام هاخد Ergo One، أعمل إيه؟"
    ])

    run_scenario(client, db, "Low-Data", "visitor_Low", [
        "السلام عليكم"
    ])

if __name__ == "__main__":
    main()
