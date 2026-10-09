import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .demo_data import FEEDBACK, PRODUCTS
from .llm_client import LLMConfigurationError, LLMRequestError, chat_completion
from .models import AgentResult, AnalysisRun, Recommendation, Workflow

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


def _business_facts() -> list[str]:
    facts: list[str] = []
    for product in PRODUCTS:
        delta = product["units_sold_7d"] - product["units_sold_prev_7d"]
        facts.extend([
            f"{product['name']} sold {product['units_sold_7d']} units in the last 7 days and {product['units_sold_prev_7d']} in the previous 7 days (change: {delta:+} units).",
            f"{product['name']} has {product['stock']} units in demo stock.",
            f"{product['name']} is listed at A${product['price']:.2f}; cost and margin data are unavailable.",
        ])
    names = {p["id"]: p["name"] for p in PRODUCTS}
    for feedback in FEEDBACK:
        facts.append(f"Customer feedback for {names.get(feedback['product_id'], 'an unknown product')}: {feedback['content']}")
    facts.append("No live campaign history, supplier lead-time feed, competitor data, or real store data is connected.")
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


def _run_agent(name: str, question: str, flow: Workflow, facts: list[str]) -> AgentResult:
    now = datetime.now(timezone.utc)
    system = (
        f"You are the {name} in a retail multi-agent system. {AGENT_TASKS[name]} "
        "Use only the supplied demo facts. Never invent data, external events, causes, or calculations. "
        "Return one JSON object with string 'summary', array 'evidence' containing exact supplied fact sentences, "
        "and array 'limitations'. Keep it concise and state uncertainty."
    )
    user = json.dumps({"workflow": flow, "owner_question": question, "available_facts": facts}, ensure_ascii=False)
    result = _parse_json_object(chat_completion(system, user))
    evidence = [line for line in _strings(result.get("evidence")) if line in facts]
    return AgentResult(
        agent=name,
        status="completed",
        summary=str(result.get("summary", "Reviewed the available demo facts."))[:1000],
        evidence=evidence,
        limitations=_strings(result.get("limitations")) or ["Illustrative demo records only; no live store integration."],
        completed_at=now,
    )


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


def run_llm(question: str, workflow: Workflow | None = None) -> AnalysisRun:
    flow = workflow or infer_workflow(question)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    facts = _business_facts()
    results: dict[str, AgentResult] = {}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
        futures = {pool.submit(_run_agent, name, question, flow, facts): name for name in AGENTS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except LLMConfigurationError:
                raise
            except LLMRequestError:
                errors.append(name)
                results[name] = AgentResult(
                    agent=name, status="failed", summary="This agent could not return a valid result.",
                    evidence=[], limitations=["Model response unavailable or invalid; no result was inferred."],
                    completed_at=datetime.now(timezone.utc),
                )

    agents = [results[name] for name in AGENTS]
    available = [agent for agent in agents if agent.status == "completed"]
    if not available:
        raise LLMAnalysisError("All specialist agents failed to return a result. Check the provider, region, key, and model configuration.")

    evidence_pool = list(dict.fromkeys(line for agent in available for line in agent.evidence))
    manager_error = False
    try:
        manager_system = (
            "You are the Manager Agent for a small independent retailer. Integrate specialist findings into one useful, "
            "cautious recommendation. Use only the supplied facts and agent results. Do not invent causes, forecasts, "
            "supplier lead times, margins, campaigns, or customer segments. The output is advisory; never claim an action "
            "was executed. Return a JSON object with string 'title', string 'action', 'priority' (high/medium/low), "
            "array 'evidence' copied exactly from the supplied specialist evidence, and string 'confidence'."
        )
        manager_user = json.dumps({
            "workflow": flow, "owner_question": question,
            "specialist_results": [agent.model_dump(mode="json") for agent in agents],
            "evidence_pool": evidence_pool,
        }, ensure_ascii=False)
        manager = _parse_json_object(chat_completion(manager_system, manager_user))
        title = str(manager.get("title", "Retail analysis recommendation"))[:180]
        action = str(manager.get("action", "Review the available evidence before taking action."))[:1200]
        priority = manager.get("priority") if manager.get("priority") in ("high", "medium", "low") else "medium"
        manager_evidence = [line for line in _strings(manager.get("evidence")) if line in evidence_pool]
        evidence = manager_evidence or evidence_pool[:5]
        confidence = str(manager.get("confidence", "Low to moderate: based on a small, seeded sample."))[:300]
    except LLMConfigurationError:
        raise
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
    limitations = [
        "All business records are illustrative seeded examples; no live store data is connected.",
        "No cost, supplier lead-time, competitor, or campaign history is available.",
    ]
    if errors:
        limitations.append("Partial analysis: unavailable agents: " + ", ".join(errors) + ".")
    if manager_error:
        limitations.append("Manager synthesis was unavailable; a conservative fallback recommendation is shown.")
    status = "completed" if not errors and not manager_error else "partial"
    return AnalysisRun(
        id=run_id, question=question, workflow=flow, status=status, data_mode="llm",
        created_at=now, agents=agents, recommendations=[recommendation], limitations=limitations,
    )


def run_demo(question: str, workflow: Workflow | None = None) -> AnalysisRun:
    flow = workflow or infer_workflow(question)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    agents = []
    for name in AGENTS:
        evidence = []
        summary = "Reviewed the available demo records for this workflow."
        if name == "Sales Agent":
            for product in PRODUCTS:
                diff = product["units_sold_7d"] - product["units_sold_prev_7d"]
                evidence.append(f"{product['name']}: {diff:+} units week-over-week ({product['units_sold_7d']} vs {product['units_sold_prev_7d']}).")
            summary = "Compared the latest 7 days with the prior 7 days using seeded sales totals."
        elif name == "Inventory Agent":
            evidence = [f"{p['name']}: {p['stock']} units currently in demo stock." for p in PRODUCTS]
            summary = "Checked current demo stock and estimated near-term pressure from recent unit sales."
        elif name == "Pricing Agent":
            evidence = [f"{p['name']}: listed demo price A${p['price']:.2f}. No margin or competitor data is available." for p in PRODUCTS]
            summary = "Reviewed listed prices; the demo dataset has no cost or competitor benchmark."
        else:
            evidence = ["No live campaign-performance feed is connected."]
            summary = "Checked available promotion context; campaign records are not included in this first slice."
        agents.append(AgentResult(agent=name, status="completed", summary=summary, evidence=evidence, limitations=["Deterministic demo data only; no live store integration."], completed_at=now))

    if flow == "overstock":
        title, action, risk = "Review Coastal Oat Biscuits clearance options", "Consider a short, low-scale bundle test and review sell-through before extending it.", False
    elif flow == "demand_spike":
        title, action, risk = "Protect Wattle Hand Balm availability", "Check supplier lead time and prepare a replenishment plan; pause any broad promotion until stock cover is confirmed.", True
    elif flow == "feedback_analysis":
        title, action, risk = "Investigate availability feedback", "Review repeat stock-out reports for Harbour Blend Coffee and confirm shelf replenishment practices.", False
    else:
        title, action, risk = "Investigate Harbour Blend Coffee sales decline", "Check whether repeated stock-outs and reduced weekly sales are connected before changing price or campaign spend.", False

    recommendation = Recommendation(
        id=str(uuid4()), title=title, priority="high" if risk else "medium", action=action,
        evidence=["Harbour Blend Coffee sales: 21 units this week vs 34 last week.", "Harbour Blend Coffee demo stock: 12 units.", "One demo customer comment mentions two stock-outs this month."],
        confidence="Low to moderate: based on a small, seeded sample.", high_risk=risk,
        status="pending_approval" if risk else "advisory",
        approval_note="Approval records an owner decision in this prototype only. No real price, stock, or campaign action will occur." if risk else "Advisory only; no operational change is executed.",
    )
    limitation = ["Demo records are illustrative, not live business data.", "No cost, supplier lead-time, competitor, or campaign history is connected."]
    return AnalysisRun(id=run_id, question=question, workflow=flow, status="completed", data_mode="demo", created_at=now, agents=agents, recommendations=[recommendation], limitations=limitation)
