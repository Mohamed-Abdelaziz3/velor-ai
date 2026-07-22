import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from database import CommercialDecisionLineage, LeadEvidence, Message, Lead

def _get_truth_class(value: Any, default: str = "UNKNOWN") -> str:
    if value is None:
        return "UNKNOWN"
    return default

def get_canonical_commercial_view(db: Session, company_id: str, lead_id: int) -> Dict[str, Any]:
    return get_canonical_commercial_view_batch(db, company_id, [lead_id]).get(lead_id, _empty_view(company_id, lead_id))

def get_canonical_commercial_view_batch(db: Session, company_id: str, lead_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    from services.product_context_service import get_company_products

    leads = db.query(Lead).filter(Lead.company_id == company_id, Lead.id.in_(lead_ids)).all()
    if not leads:
        return {}
        
    user_ids = []
    lead_id_by_uid = {}
    for l in leads:
        uid = l.external_customer_id if l.channel_type == "VELOR_WEB_CHAT" else (l.customer_provided_phone or l.phone or l.whatsapp_number or l.whatsapp_jid)
        if uid:
            user_ids.append(uid)
            lead_id_by_uid[uid] = l.id

    messages = db.query(Message).filter(
        Message.company_id == company_id, 
        Message.user_id.in_(user_ids), 
        Message.direction == "incoming",
        Message.sender.in_(("user", "customer")),
    ).order_by(Message.id.desc()).all()
    
    latest_msg_by_lead = {}
    for m in messages:
        lid = lead_id_by_uid.get(m.user_id)
        if lid and lid not in latest_msg_by_lead:
            latest_msg_by_lead[lid] = m
            
    lineages = db.query(CommercialDecisionLineage).filter(
        CommercialDecisionLineage.company_id == company_id, 
        CommercialDecisionLineage.lead_id.in_(lead_ids)
    ).order_by(CommercialDecisionLineage.id.desc()).all()
    
    latest_lineage_by_lead = {}
    for lin in lineages:
        if lin.lead_id not in latest_lineage_by_lead:
            latest_lineage_by_lead[lin.lead_id] = lin

    evidence = db.query(LeadEvidence).filter(
        LeadEvidence.company_id == company_id, 
        LeadEvidence.lead_id.in_(lead_ids)
    ).order_by(LeadEvidence.id.desc()).all()
    
    evidence_by_lead = {lid: [] for lid in lead_ids}
    for e in evidence:
        evidence_by_lead[e.lead_id].append(e)

    # One company-scoped catalog read for the whole batch. Advisory text never
    # supplies a price; a price is exposed only for an exact trusted catalog
    # product reference.
    trusted_products = {
        str(getattr(product, "name", "")).casefold(): product
        for product in get_company_products(db, company_id)
        if getattr(product, "name", None)
    }

    result = {}
    for lead in leads:
        lid = lead.id
        msg = latest_msg_by_lead.get(lid)
        lin = latest_lineage_by_lead.get(lid)
        evs = evidence_by_lead.get(lid, [])
        
        is_stale = False
        status = "UNKNOWN"
        reason = None
        
        if lin and msg:
            if lin.source_message_internal_id == msg.internal_message_id:
                status = "CURRENT"
            else:
                if msg.created_at and lin.created_at and msg.created_at > lin.created_at:
                    status = "PENDING_RECOMPUTE"
                    is_stale = True
                else:
                    status = "STALE"
                    is_stale = True
        elif lin:
            status = "STALE"
            is_stale = True
        elif msg:
            status = "PENDING_RECOMPUTE"
            is_stale = True
            
        decision_json = {}
        if lin:
            try:
                decision_json = json.loads(lin.decision_json)
            except Exception:
                pass
                
        budget_val = None
        budget_constraint = None
        budget_ev_ids = []
        active_objection_val = None
        active_objection_ev_ids = []
        purchase_status_val = None
        purchase_status_ev_ids = []
        product_refs = []
        
        for e in reversed(evs): 
            e_data = {}
            if e.metadata_json:
                try:
                    e_data = json.loads(e.metadata_json)
                except Exception:
                    pass
                    
            if e.evidence_type == "objection":
                active_objection_val = e.normalized_value
                active_objection_ev_ids = [e.id]
                if e.normalized_value in ["NONE", "RESOLVED"]:
                    active_objection_val = None
                    active_objection_ev_ids = []
            elif e.evidence_type == "budget":
                try:
                    budget_val = int(e.normalized_value)
                    budget_constraint = e_data.get("constraint_type", "MAX_BUDGET")
                    budget_ev_ids = [e.id]
                except Exception:
                    pass
            elif e.evidence_type == "product_interest":
                product = trusted_products.get(str(e.normalized_value or "").casefold())
                trusted_price = {
                    "amount": getattr(product, "price", None),
                    "currency": getattr(product, "currency", None),
                    "truth_class": "OBSERVED",
                    "source_type": "COMPANY_KNOWLEDGE",
                } if product and getattr(product, "price", None) is not None else {
                    "amount": None,
                    "currency": None,
                    "truth_class": "UNKNOWN",
                    "source_type": "COMPANY_KNOWLEDGE",
                }
                product_refs.append({
                    "product_key": e.normalized_value,
                    "display_name": e.normalized_value,
                    "relation": "SELECTED",
                    "truth_class": "OBSERVED",
                    "source_message_internal_id": e.message_internal_id,
                    "evidence_ids": [e.id],
                    "trusted_price": trusted_price,
                })
            elif e.evidence_type == "purchase_statement":
                purchase_status_val = e.normalized_value
                purchase_status_ev_ids = [e.id]

        if purchase_status_val in ["READY_TO_BUY", "PURCHASE_EXECUTION_REQUESTED", "PURCHASE_EXECUTION_REQUIRED", "FACILITATE_PURCHASE"]:
            if lin and lin.objective in ["DISCOVERY", "EVALUATION"]:
                is_stale = True
                status = "STALE"

        view = {
            "canonical_commercial": {
                "company_id": company_id,
                "customer_id": lid,
                "channel_scope": "VELOR_WEB_CHAT",
                "as_of_message_id": msg.internal_message_id if msg else None,
                "as_of_timestamp": msg.created_at.isoformat() if msg and msg.created_at else None,
                "latest_inbound_customer_message_id": msg.internal_message_id if msg else None,
                "processing_status": status,
                "sales_state": {
                    "value": decision_json.get("sales_state") if lin else None,
                    "truth_class": _get_truth_class(decision_json.get("sales_state"), "DETERMINISTICALLY_DERIVED"),
                    "source_message_id": lin.source_message_id if lin else None,
                    "lineage_id": lin.id if lin else None,
                    "observed_at": lin.created_at.isoformat() if lin and lin.created_at else None
                },
                "intent": {
                    "value": decision_json.get("intent") if lin else None,
                    "truth_class": _get_truth_class(decision_json.get("intent"), "DETERMINISTICALLY_DERIVED"),
                    "source_message_id": lin.source_message_id if lin else None,
                    "lineage_id": lin.id if lin else None,
                    "observed_at": lin.created_at.isoformat() if lin and lin.created_at else None
                },
                "momentum": {
                    "value": decision_json.get("momentum") if lin else None,
                    "truth_class": _get_truth_class(decision_json.get("momentum"), "DETERMINISTICALLY_DERIVED"),
                    "source_message_id": lin.source_message_id if lin else None,
                    "lineage_id": lin.id if lin else None,
                    "observed_at": lin.created_at.isoformat() if lin and lin.created_at else None
                },
                "active_objection": {
                    "value": active_objection_val,
                    "truth_class": "OBSERVED" if active_objection_val else "UNKNOWN",
                    "evidence_ids": active_objection_ev_ids,
                },
                "budget": {
                    "amount": budget_val,
                    "currency": "EGP",
                    "constraint_type": budget_constraint,
                    "truth_class": "OBSERVED" if budget_val else "UNKNOWN",
                    "evidence_ids": budget_ev_ids
                },
                "product_references": product_refs,
                "objective": {
                    "value": lin.objective if lin else None,
                    "truth_class": _get_truth_class(lin.objective if lin else None, "DETERMINISTICALLY_DERIVED"),
                    "lineage_id": lin.id if lin else None,
                },
                "strategy": {
                    "value": lin.strategy if lin else None,
                    "truth_class": _get_truth_class(lin.strategy if lin else None, "DETERMINISTICALLY_DERIVED"),
                    "lineage_id": lin.id if lin else None,
                },
                "next_move": {
                    "value": lin.next_move if lin else None,
                    "truth_class": _get_truth_class(lin.next_move if lin else None, "DETERMINISTICALLY_DERIVED"),
                    "lineage_id": lin.id if lin else None,
                },
                "escalation": {
                    "required": lin.escalation_required if lin else False,
                    "reason_code": None,
                    "truth_class": "DETERMINISTICALLY_DERIVED" if lin else "UNKNOWN",
                    "evidence_ids": []
                },
                "owner_attention": {
                    "required": decision_json.get("owner_attention_required", False) if lin else False,
                    "reason_code": decision_json.get("owner_attention_reason"),
                    "recommended_action": None,
                    "truth_class": "DETERMINISTICALLY_DERIVED" if lin else "UNKNOWN",
                    "evidence_ids": []
                },
                "purchase_status": {
                    "value": purchase_status_val,
                    "truth_class": "OBSERVED" if purchase_status_val else "UNKNOWN",
                    "evidence_ids": purchase_status_ev_ids
                },
                "stale_status": is_stale,
                "stale_reason": reason,
                "known_facts": [],
                "unknown_fields": []
            }
        }
        result[lid] = view

    return result

def _empty_view(company_id: str, lead_id: int) -> Dict[str, Any]:
    return {
        "canonical_commercial": {
            "company_id": company_id,
            "customer_id": lead_id,
            "sales_state": {"value": None, "truth_class": "UNKNOWN"},
            "intent": {"value": None, "truth_class": "UNKNOWN"},
            "momentum": {"value": None, "truth_class": "UNKNOWN"},
            "active_objection": {"value": None, "truth_class": "UNKNOWN"},
            "budget": {"value": None, "truth_class": "UNKNOWN"},
            "objective": {"value": None, "truth_class": "UNKNOWN"},
            "strategy": {"value": None, "truth_class": "UNKNOWN"},
            "next_move": {"value": None, "truth_class": "UNKNOWN"},
            "escalation": {"required": False, "truth_class": "UNKNOWN"},
            "owner_attention": {"required": False, "truth_class": "UNKNOWN"},
            "purchase_status": {"value": None, "truth_class": "UNKNOWN"},
            "stale_status": False
        }
    }
