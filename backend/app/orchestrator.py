import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .demo_data import FEEDBACK, PRODUCTS
from .llm_client import LLMRequestError
from .models import AgentResult, AnalysisRun, Recommendation, Workflow
from .crewai_flow import run_retail_analysis_flow

AGENTS = ["Sales Agent", "Inventory Agent", "Pricing Agent", "Marketing Agent"]
AGENT_TASKS = {
    "Sales Agent": "Analyse sales trend, week-over-week movement, product performance, and any limits in the available sales history.",
    "Inventory Agent": "Assess current stock and recent sales velocity for stock-out or overstock risk. Do not invent supplier lead times or order quantities.",
    "Pricing Agent": "Assess listed prices against only the available sales, stock, and feedback facts. No cost, margin, or competitor benchmark is available.",
    "Marketing Agent": "Assess customer feedback and promotion context. No campaign-performance feed exists; do not invent past campaigns or customer segments.",
}


class LLMAnalysisError(Exception):
    pass


def infer_workflow(question: str) -> Workflow:
    q = question.lower()
    if any(term in q for term in ("feedback", "review", "complaint", "customer")):
        return "feedback_analysis"
    if any(term in q for term in ("overstock", "overstocked", "clearance", "slow-moving", "积压", "清仓")):
        return "overstock"
    if any(term in q for term in ("spike", "surge", "sudden", "demand increase", "缺货", "暴涨")):
        return "demand_spike"
    return "sales_decline"


def _business_facts(products: list[dict] = PRODUCTS, feedback_records: list[dict] = FEEDBACK) -> list[str]:
    facts: list[str] = []
    for product in products:
        delta = product["units_sold_7d"] - product["units_sold_prev_7d"]
        facts.extend([
            f"{product['name']} sold {product['units_sold_7d']} units in the last 7 days and {product['units_sold_prev_7d']} in the previous 7 days (change: {delta:+} units).",
            f"{product['name']} has {product['stock']} units in stock.",
            f"{product['name']} is listed at A${product['price']:.2f}; cost and margin data are unavailable.",
        ])
    names = {p["id"]: p["name"] for p in products}
    for feedback in feedback_records:
        facts.append(f"Customer feedback for {names.get(feedback['product_id'], 'an unknown product')}: {feedback['content']}")
    facts.append("No live campaign history, supplier lead-time feed, or competitor data is available in the connected records.")
    return facts


def _dataset_context(facts: list[str]) -> str:
    return "\n".join(f"- {fact}" for fact in facts)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMRequestError("The model returned data that did not match the expected JSON format.") from None
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            raise LLMRequestError("The model returned data that did not match the expected JSON format.") from None
    if not isinstance(value, dict):
        raise LLMRequestError("The model returned data that did not match the expected JSON format.")
    return value


def _strings(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip()[:500] for item in value if isinstance(item, str) and item.strip()][:limit]


def _parse_specialist(_name: str, raw: str, facts: list[str]) -> dict[str, Any]:
    result = _parse_json_object(raw)
    return {
        "status": "completed",
        "summary": str(result.get("summary", "Reviewed the available demo facts."))[:1000],
        "evidence": [line for line in _strings(result.get("evidence")) if line in facts],
        "limitations": _strings(result.get("limitations")) or [
            "Use only the supplied records; no external store systems are connected."
        ],
    }


def _risk_requires_approval(action: str, flow: Workflow) -> bool:
    if flow == "demand_spike":
        return True
    text = action.lower()
    risk_terms = (
        "price change", "change price", "price adjustment", "discount", "promotion", "campaign",
        "restock", "replenish", "purchase order", "bulk order", "bulk restock", "advert",
        "降价", "调价", "折扣", "促销", "补货", "批量采购", "广告",
    )
    return any(term in text for term in risk_terms)


def _fallback_recommendation(flow: Workflow, agent_results: list[AgentResult], facts: list[str]) -> tuple[str, str, str, list[str]]:
    fallback = {
        "sales_decline": ("Investigate the sales movement", "Review the available sales and stock facts before changing price or campaign plans.", "low"),
        "overstock": ("Review slow-moving stock", "Check the stock and sales evidence, then consider a small reversible clearance experiment.", "medium"),
        "demand_spike": ("Protect product availability", "Review current stock and sales velocity; confirm supplier lead time before any replenishment decision.", "high"),
        "feedback_analysis": ("Review customer feedback themes", "Investigate the feedback against the available sales and inventory facts before making operational changes.", "medium"),
    }
    title, action, priority = fallback[flow]
    agent_evidence = [line for agent in agent_results for line in agent.evidence]
    evidence = list(dict.fromkeys(agent_evidence))[:5] or facts[:3]
    return title, action, priority, evidence


def run_llm(question: str, workflow: Workflow | None = None, *, products: list[dict] = PRODUCTS,
            feedback_records: list[dict] = FEEDBACK, data_mode: str = "llm") -> AnalysisRun:
    flow = workflow or infer_workflow(question)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    facts = _business_facts(products, feedback_records)
    manager_system = (
        "You are the Manager Agent for a small independent retailer. Integrate specialist findings into one useful, "
        "cautious recommendation. Use only the supplied facts and agent results. Do not invent causes, forecasts, "
        "supplier lead times, margins, campaigns, or customer segments. The output is advisory; never claim an action "
        "was executed. Return a JSON object with string 'title', string 'action', 'priority' (high/medium/low), "
        "array 'evidence' copied exactly from the supplied specialist evidence, and string 'confidence'."
    )
    execution = run_retail_analysis_flow(
        question=question,
        workflow=flow,
        facts=facts,
        agent_tasks=AGENT_TASKS,
        manager_system=manager_system,
        parse_specialist=_parse_specialist,
    )
    results: dict[str, AgentResult] = {}
    errors = list(execution.specialist_errors)
    for name in AGENTS:
        result = execution.specialist_results.get(name)
        completed_at = result.get("completed_at", datetime.now(timezone.utc)) if result else datetime.now(timezone.utc)
        if not result or result.get("status") != "completed":
            results[name] = AgentResult(
                agent=name, status="failed", summary="This agent could not return a valid result.",
                evidence=[], limitations=["Model response unavailable or invalid; no result was inferred."],
                completed_at=completed_at,
            )
            if name not in errors:
                errors.append(name)
            continue
        results[name] = AgentResult(
            agent=name,
            status="completed",
            summary=result["summary"],
            evidence=result["evidence"],
            limitations=result["limitations"],
            completed_at=completed_at,
        )

    agents = [results[name] for name in AGENTS]
    available = [agent for agent in agents if agent.status == "completed"]
    if not available:
        raise LLMAnalysisError("All specialist agents failed to return a result. Check the provider, region, key, and model configuration.")

    evidence_pool = list(dict.fromkeys(line for agent in available for line in agent.evidence))
    manager_error = execution.manager_error
    try:
        if not execution.manager_output:
            raise LLMRequestError("The Manager Agent did not return a valid result.")
        manager = _parse_json_object(execution.manager_output)
        title = str(manager.get("title", "Retail analysis recommendation"))[:180]
        action = str(manager.get("action", "Review the available evidence before taking action."))[:1200]
        priority = manager.get("priority") if manager.get("priority") in ("high", "medium", "low") else "medium"
        manager_evidence = [line for line in _strings(manager.get("evidence")) if line in evidence_pool]
        evidence = manager_evidence or evidence_pool[:5]
        confidence = str(manager.get("confidence", "Low to moderate: based on a small, seeded sample."))[:300]
    except LLMRequestError:
        manager_error = True
        title, action, priority, evidence = _fallback_recommendation(flow, available, facts)
        confidence = "Low: manager synthesis was unavailable; review the specialist results."

    high_risk = _risk_requires_approval(action, flow)
    recommendation = Recommendation(
        id=str(uuid4()), title=title, priority=priority, action=action,
        evidence=evidence, confidence=confidence, high_risk=high_risk,
        status="pending_approval" if high_risk else "advisory",
        approval_note=(
            "Owner approval records a decision in this prototype only. No external price, stock, or campaign action will occur."
            if high_risk else "Advisory only; no operational change is executed."
        ),
    )
    limitations = (["Business records came from the configured Supabase database; they may still be synthetic demo records."]
                   if data_mode == "supabase_llm" else
                   ["All business records are illustrative seeded examples; no live store data is connected."])
    limitations.append("No cost, supplier lead-time, competitor, or campaign history is available.")
    if errors:
        limitations.append("Partial analysis: unavailable agents: " + ", ".join(errors) + ".")
    if manager_error:
        limitations.append("Manager synthesis was unavailable; a conservative fallback recommendation is shown.")
    status = "completed" if not errors and not manager_error else "partial"
    return AnalysisRun(
        id=run_id, question=question, workflow=flow, status=status, data_mode=data_mode,
        created_at=now, agents=agents, recommendations=[recommendation], limitations=limitations,
    )


def run_demo(question: str, workflow: Workflow | None = None, *, products: list[dict] = PRODUCTS,
             feedback_records: list[dict] = FEEDBACK, data_mode: str = "demo") -> AnalysisRun:
    flow = workflow or infer_workflow(question)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    agents = []
    for name in AGENTS:
        evidence = []
        summary = "Reviewed the available business records for this workflow."
        if name == "Sales Agent":
            for product in products:
                diff = product["units_sold_7d"] - product["units_sold_prev_7d"]
                evidence.append(f"{product['name']}: {diff:+} units week-over-week ({product['units_sold_7d']} vs {product['units_sold_prev_7d']}).")
            summary = "Compared the latest 7 days with the prior 7 days using the available sales records."
        elif name == "Inventory Agent":
            evidence = [f"{p['name']}: {p['stock']} units currently in stock." for p in products]
            summary = "Checked current stock and estimated near-term pressure from recent unit sales."
        elif name == "Pricing Agent":
            evidence = [f"{p['name']}: listed price A${p['price']:.2f}. No margin or competitor data is available." for p in products]
            summary = "Reviewed listed prices; no cost or competitor benchmark is available."
        else:
            product_names = {product["id"]: product["name"] for product in products}
            feedback_facts = [f"Customer feedback for {product_names.get(item['product_id'], 'a product')}: {item['content']}" for item in feedback_records]
            evidence = ["No live campaign-performance feed is connected.", *feedback_facts]
            summary = "Reviewed the available demo feedback; no campaign-performance feed is connected."
        agent_limit = "Deterministic analysis of Supabase records; other store systems are not connected." if data_mode == "supabase" else "Deterministic demo data only; no live store integration."
        agents.append(AgentResult(agent=name, status="completed", summary=summary, evidence=evidence, limitations=[agent_limit], completed_at=now))

    if flow == "overstock":
        title, action, risk = "Review Coastal Oat Biscuits clearance options", "Consider a short, low-scale bundle test and review sell-through before extending it.", False
    elif flow == "demand_spike":
        title, action, risk = "Protect Wattle Hand Balm availability", "Check supplier lead time and prepare a replenishment plan; pause any broad promotion until stock cover is confirmed.", True
    elif flow == "feedback_analysis":
        title, action, risk = "Investigate availability feedback", "Review repeat stock-out reports for Harbour Blend Coffee and confirm shelf replenishment practices.", False
    else:
        title, action, risk = "Investigate Harbour Blend Coffee sales decline", "Check whether repeated stock-outs and reduced weekly sales are connected before changing price or campaign spend.", False

    coffee = next((product for product in products if product["id"] == "P-001"), products[0] if products else None)
    recommendation_evidence = ([f"{coffee['name']} sales: {coffee['units_sold_7d']} units this week vs {coffee['units_sold_prev_7d']} last week.",
                                f"{coffee['name']} stock: {coffee['stock']} units."] if coffee else ["No product records are available."])
    feedback_example = next((item for item in feedback_records if item.get("product_id") == (coffee or {}).get("id")), None)
    if feedback_example:
        recommendation_evidence.append(f"Customer feedback: {feedback_example['content']}")
    if flow == "feedback_analysis":
        product_names = {product["id"]: product["name"] for product in products}
        recommendation_evidence = [f"{product_names.get(item['product_id'], 'Product')}: {item['content']}" for item in feedback_records[:3]]
        if not recommendation_evidence:
            recommendation_evidence = ["No customer feedback has been submitted yet."]
    recommendation = Recommendation(
        id=str(uuid4()), title=title, priority="high" if risk else "medium", action=action,
        evidence=recommendation_evidence,
        confidence="Low to moderate: based on a small, seeded sample.", high_risk=risk,
        status="pending_approval" if risk else "advisory",
        approval_note="Approval records an owner decision in this prototype only. No real price, stock, or campaign action will occur." if risk else "Advisory only; no operational change is executed.",
    )
    limitation = (["Records were loaded from Supabase; the seeded records are illustrative, not live-store data."]
                  if data_mode == "supabase" else ["Demo records are illustrative, not live business data."])
    limitation.append("No cost, supplier lead-time, competitor, or campaign history is connected.")
    return AnalysisRun(id=run_id, question=question, workflow=flow, status="completed", data_mode=data_mode, created_at=now, agents=agents, recommendations=[recommendation], limitations=limitation)
