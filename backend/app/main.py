import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .demo_data import FEEDBACK, PRODUCTS
from .llm_client import LLMConfigurationError, LLMRequestError
from .models import (AnalysisRun, AnalyzeRequest, CustomerQuestion, DecisionRequest, FeedbackEscalation,
                     FeedbackSubmission, InventoryMovementSubmission, OwnerLogin)
from . import auth
from .orchestrator import (LLMAnalysisError, WORKFLOW_CLARIFICATION_MESSAGE, infer_workflow,
                           run_demo, run_llm)
from . import supabase_store
from .customer_qa import answer_customer_question
from .insights import feedback_insights, product_indicators

app = FastAPI(title="SoloRetail AI API", version="0.2.0", description="Retail analysis prototype with demo and DashScope-compatible LLM modes")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:4173"], allow_methods=["*"], allow_headers=["*"])
RUNS: dict[str, AnalysisRun] = {}
AUDIT: list[dict] = []
INVENTORY_MOVEMENTS: list[dict] = []
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:\+?\d[\d().\s-]{6,}\d)(?![A-Za-z0-9])")


def mask_contact_details(text: str) -> tuple[str, bool]:
    masked, email_count = EMAIL_PATTERN.subn("[email masked]", text)
    masked, phone_count = PHONE_PATTERN.subn("[phone masked]", masked)
    return masked, bool(email_count or phone_count)


def current_data_mode() -> str:
    return os.getenv("DATA_MODE", "demo").strip().lower()


def llm_configured() -> bool:
    return all(os.getenv(name, "").strip() for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"))


def _spread_demo_total(total: int, weights: list[int]) -> list[int]:
    weight_sum = sum(weights)
    scaled = [total * weight for weight in weights]
    values = [value // weight_sum for value in scaled]
    remainder = total - sum(values)
    for index in sorted(range(len(weights)), key=lambda item: scaled[item] % weight_sum, reverse=True)[:remainder]:
        values[index] += 1
    return values


def _demo_product_sales_series(product: dict, days: int) -> list[dict]:
    """Spread weekly demo totals across days and label the result as illustrative."""
    today = supabase_store.business_as_of_date()
    first_day = today - timedelta(days=days - 1)
    current_week = _spread_demo_total(int(product.get("units_sold_7d", 0)), [1, 2, 1, 2, 3, 4, 5])
    previous_week = _spread_demo_total(int(product.get("units_sold_prev_7d", 0)), [5, 4, 3, 2, 2, 1, 1])
    points = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        if days == 7:
            quantity = current_week[offset]
        elif offset < 7:
            quantity = previous_week[offset]
        else:
            quantity = current_week[offset - 7]
        points.append({"date": day.isoformat(), "quantity": quantity,
                       "revenue": round(quantity * float(product.get("price", 0)), 2)})
    return points


@app.get("/health")
def health():
    mode = current_data_mode()
    return {"status": "ok", "data_mode": mode,
            "llm_configured": llm_configured() if mode in ("llm", "supabase_llm") else False,
            "supabase_configured": supabase_store.configured()}


@app.get("/api/auth/config")
def auth_config():
    return {"authentication_required": auth.enabled()}


@app.post("/api/auth/login")
def owner_login(request: OwnerLogin):
    if not auth.enabled():
        raise HTTPException(status_code=409, detail="Owner login is not enabled for this local prototype.")
    token, session = auth.login(request.email, request.password)
    return {"token": token, "session": session, "expires_in_seconds": 8 * 60 * 60}


@app.get("/api/auth/session")
def owner_session(authorization: str | None = Header(default=None)):
    session = auth.session_for_token(auth.token_from_header(authorization))
    if session is None:
        raise HTTPException(status_code=401, detail="Your session is missing or has expired.")
    return {"session": session}


@app.post("/api/auth/logout", status_code=204)
def owner_logout(authorization: str | None = Header(default=None)):
    auth.logout(authorization)


@app.get("/api/dashboard")
def dashboard(_owner: dict = Depends(auth.require_owner)):
    mode = current_data_mode()
    as_of = supabase_store.business_as_of_date()
    if mode.startswith("supabase"):
        try:
            products, feedback_records = supabase_store.load_business_data()
            runs = supabase_store.load_runs(limit=5)
            audit = supabase_store.load_audit(limit=10)
            movements = supabase_store.load_inventory_movements(limit=12)
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"data_mode": mode, "as_of": datetime.now(timezone.utc), "business_as_of_date": as_of.isoformat(), "products": products,
                "feedback_count": len(feedback_records), "feedback": feedback_records,
                "runs": runs, "audit": audit, "movements": movements, "insights": {"products": product_indicators(products), "feedback": feedback_insights(feedback_records)}}
    return {"data_mode": current_data_mode(), "as_of": datetime.now(timezone.utc), "business_as_of_date": as_of.isoformat(), "products": PRODUCTS, "feedback_count": len(FEEDBACK), "feedback": FEEDBACK, "runs": list(RUNS.values())[-5:], "audit": AUDIT[-10:], "movements": INVENTORY_MOVEMENTS[-12:], "insights": {"products": product_indicators(PRODUCTS), "feedback": feedback_insights(FEEDBACK)}}


@app.get("/api/products/{product_id}/trend")
def product_trend(product_id: str, days: int = 7, _owner: dict = Depends(auth.require_owner)):
    if days not in (7, 14):
        raise HTTPException(status_code=422, detail="Choose a 7-day or 14-day trend.")
    mode = current_data_mode()
    if mode.startswith("supabase"):
        try:
            sales = supabase_store.load_product_sales_series(product_id, days)
            movements = supabase_store.load_inventory_movements(limit=50, product_id=product_id)
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"product_id": product_id, "days": days, "sales": sales, "movements": movements,
                "sales_source": "recorded"}

    product = next((item for item in PRODUCTS if item["id"] == product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    movements = [item for item in reversed(INVENTORY_MOVEMENTS) if item["product_id"] == product_id][:50]
    return {"product_id": product_id, "days": days,
            "sales": _demo_product_sales_series(product, days), "movements": movements,
            "sales_source": "illustrative"}


@app.post("/api/analyze", response_model=AnalysisRun)
def analyze(request: AnalyzeRequest, _owner: dict = Depends(auth.require_owner)):
    workflow = request.workflow or infer_workflow(request.question)
    if workflow is None:
        raise HTTPException(status_code=422, detail=WORKFLOW_CLARIFICATION_MESSAGE)
    mode = current_data_mode()
    use_supabase = mode in ("supabase", "supabase_llm")
    use_llm = mode in ("llm", "supabase_llm")
    products = PRODUCTS
    feedback_records = FEEDBACK
    if use_supabase:
        try:
            products, feedback_records = supabase_store.load_business_data()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    scope: dict[str, str] = {}
    if request.product_id:
        selected_product = next((product for product in products if product["id"] == request.product_id), None)
        if selected_product is None:
            raise HTTPException(status_code=422, detail="The selected analysis product is not available.")
        scope = {"product_id": selected_product["id"], "product_name": selected_product["name"]}
        products = [selected_product]
        feedback_records = [item for item in feedback_records if item.get("product_id") == request.product_id]
    if use_llm:
        try:
            run = run_llm(request.question, workflow, products=products, feedback_records=feedback_records,
                          data_mode="supabase_llm" if use_supabase else "llm",
                          simulated_failures=set(request.simulate_failures))
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except LLMAnalysisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        except LLMRequestError:
            raise HTTPException(status_code=502, detail="The configured model provider could not return a valid response.") from None
    elif mode in ("demo", "supabase"):
        run = run_demo(request.question, workflow, products=products, feedback_records=feedback_records,
                       data_mode="supabase" if use_supabase else "demo",
                       simulated_failures=set(request.simulate_failures))
    else:
        raise HTTPException(status_code=503, detail="DATA_MODE must be demo, llm, supabase, or supabase_llm.")

    run.scope = scope

    RUNS[run.id] = run
    summary_mode = "LLM-assisted analysis" if "llm" in run.data_mode else "deterministic analysis"
    failure_note = f"; controlled unavailable agents: {', '.join(request.simulate_failures)}" if request.simulate_failures else ""
    audit_summary = f"Started {run.workflow} {summary_mode} in {run.data_mode} mode{failure_note}"
    AUDIT.append({"id": str(uuid4()), "event": "analysis_created", "run_id": run.id, "summary": audit_summary, "created_at": datetime.now(timezone.utc)})
    if use_supabase:
        try:
            supabase_store.save_run(run, audit_summary=audit_summary)
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=f"Analysis completed, but its database record could not be fully saved. {exc}") from None
    return run


def _sales_ranking_request(question: str) -> tuple[str, int, bool] | None:
    q = question.casefold()
    rank_terms = (
        "lowest", "least", "smallest", "minimum", "bottom", "highest", "most", "best-selling",
        "top", "maximum", "rank", "which product", "compare", "最低", "最高", "最少", "最多",
        "排名", "哪个商品", "哪款商品", "哪种商品",
    )
    if not any(term in q for term in rank_terms):
        return None
    revenue_terms = ("revenue", "total sales", "gross sales", "sales value", "sales amount", "sales revenue", "销售额", "销售收入", "营业额", "总销售额")
    sales_terms = ("sales", "units sold", "sales volume", "quantity sold", "销量", "销售", "售出数量", "卖出")
    if not any(term in q for term in revenue_terms + sales_terms):
        return None
    metric = "revenue" if any(term in q for term in revenue_terms) else "units"
    days = 7 if any(term in q for term in ("last 7 days", "past 7 days", "last week", "最近7天", "近7天", "过去7天")) else 14
    lowest = any(term in q for term in ("lowest", "least", "smallest", "minimum", "bottom", "最低", "最少"))
    highest = any(term in q for term in ("highest", "most", "best-selling", "top", "maximum", "最高", "最多"))
    if lowest == highest:
        return None
    return metric, days, highest


@app.post("/api/assistant")
def assistant(request: AnalyzeRequest, _owner: dict = Depends(auth.require_owner)):
    """Answer simple sales rankings directly; use agents only for diagnostic workflows."""
    if request.workflow:
        run = analyze(request, _owner)
        return {"kind": "analysis", "run": run}

    workflow = infer_workflow(request.question)
    if workflow:
        run = analyze(request.model_copy(update={"workflow": workflow}), _owner)
        return {"kind": "analysis", "run": run}

    ranking = _sales_ranking_request(request.question)
    if ranking:
        metric, days, highest = ranking
        mode = current_data_mode()
        if mode.startswith("supabase"):
            try:
                products, _ = supabase_store.load_business_data()
            except supabase_store.SupabaseError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from None
        else:
            products = PRODUCTS
        values = []
        for product in products:
            if metric == "revenue":
                value = float(product.get(f"revenue_{days}d", 0)) if mode.startswith("supabase") else (
                    int(product.get("units_sold_7d", 0)) * float(product.get("price", 0))
                    + (int(product.get("units_sold_prev_7d", 0)) * float(product.get("price", 0)) if days == 14 else 0)
                )
            else:
                value = int(product.get(f"units_sold_{days}d", 0)) if mode.startswith("supabase") else (
                    int(product.get("units_sold_7d", 0))
                    + (int(product.get("units_sold_prev_7d", 0)) if days == 14 else 0)
                )
            values.append({"name": product["name"], "value": value})
        values.sort(key=lambda item: item["value"], reverse=highest)
        selected = values[0] if values else None
        as_of = supabase_store.business_as_of_date()
        first_day = as_of - timedelta(days=days - 1)
        metric_label = "sales revenue" if metric == "revenue" else "units sold"
        source = "Supabase sales records" if mode.startswith("supabase") else "illustrative demo records"
        if selected is None:
            answer = "No product sales records are available for this period."
            title = "No sales records"
        else:
            formatted = f"A${selected['value']:,.2f}" if metric == "revenue" else f"{int(selected['value'])} units"
            rank_label = "highest" if highest else "lowest"
            answer = f"{selected['name']} had the {rank_label} {metric_label} over the {days}-day period: {formatted}."
            title = f"{rank_label.title()} {metric_label} · {days} days"
        return {
            "kind": "answer", "title": title, "answer": answer,
            "evidence": [
                f"{item['name']}: {'A$' + format(item['value'], ',.2f') if metric == 'revenue' else str(int(item['value'])) + ' units'}"
                for item in values
            ],
            "period_start": first_day.isoformat(), "period_end": as_of.isoformat(),
            "data_source": source,
        }

    return {
        "kind": "clarification",
        "message": "I can answer sales-ranking questions directly or run one of the four business analyses. Which should I focus on?",
        "choices": [
            {"key": "sales_decline", "label": "Sales decline"},
            {"key": "overstock", "label": "Overstock"},
            {"key": "demand_spike", "label": "Demand spike"},
            {"key": "feedback_analysis", "label": "Customer feedback"},
        ],
    }


@app.get("/api/analyses", response_model=list[AnalysisRun])
def analyses(_owner: dict = Depends(auth.require_owner)):
    if current_data_mode().startswith("supabase"):
        try:
            return supabase_store.load_runs()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return list(RUNS.values())[::-1]


@app.post("/api/recommendations/{recommendation_id}/decision")
def decide(recommendation_id: str, request: DecisionRequest, _owner: dict = Depends(auth.require_owner)):
    if current_data_mode().startswith("supabase"):
        try:
            recommendation, _run_id = supabase_store.decide(recommendation_id, request.decision, request.note)
        except KeyError:
            raise HTTPException(status_code=404, detail="Recommendation not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"recommendation": recommendation, "executed": False,
                "message": "Decision recorded in Supabase; no external business action was executed."}
    for run in RUNS.values():
        for recommendation in run.recommendations:
            if recommendation.id == recommendation_id:
                if not recommendation.high_risk or recommendation.status != "pending_approval":
                    raise HTTPException(status_code=409, detail="This recommendation is not awaiting a high-risk approval.")
                recommendation.status = "approved" if request.decision == "approve" else "rejected"
                decision_status = "approved" if request.decision == "approve" else "rejected"
                AUDIT.append({"id": str(uuid4()), "event": f"recommendation_{decision_status}", "run_id": run.id, "recommendation_id": recommendation_id, "summary": request.note or f"Owner {decision_status} recommendation", "created_at": datetime.now(timezone.utc)})
                return {"recommendation": recommendation, "executed": False, "message": "Decision recorded in prototype; no external business action was executed."}
    raise HTTPException(status_code=404, detail="Recommendation not found.")


@app.get("/api/customer/products")
def products():
    if current_data_mode().startswith("supabase"):
        try:
            loaded_products, _ = supabase_store.load_business_data()
            return {"data_mode": current_data_mode(), "products": loaded_products}
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"data_mode": current_data_mode(), "products": PRODUCTS}


@app.post("/api/customer/ask")
def ask_customer(request: CustomerQuestion):
    if current_data_mode().startswith("supabase"):
        try:
            product_records, _ = supabase_store.load_business_data()
            promotions = supabase_store.load_active_promotions()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    else:
        product_records = PRODUCTS
        promotions = []
    return {"data_mode": current_data_mode(), **answer_customer_question(request.question, product_records, promotions)}


@app.get("/api/customer/feedback")
def feedback():
    if current_data_mode().startswith("supabase"):
        try:
            _, feedback_records = supabase_store.load_business_data()
            return {"data_mode": current_data_mode(), "feedback": feedback_records}
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"data_mode": current_data_mode(), "feedback": FEEDBACK}


@app.post("/api/feedback/{feedback_id}/escalate")
def escalate_feedback(feedback_id: str, request: FeedbackEscalation, _owner: dict = Depends(auth.require_owner)):
    if current_data_mode().startswith("supabase"):
        try:
            _, feedback_records = supabase_store.load_business_data()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    else:
        feedback_records = FEEDBACK
    if not any(str(item.get("id")) == feedback_id for item in feedback_records):
        raise HTTPException(status_code=404, detail="Feedback record not found.")
    summary = "Owner marked feedback for manual review" + (f": {request.note}" if request.note else ".")
    audit_entry = {"id": str(uuid4()), "event": "feedback_escalated", "feedback_id": feedback_id,
                   "summary": summary, "created_at": datetime.now(timezone.utc)}
    AUDIT.append(audit_entry)
    if current_data_mode().startswith("supabase"):
        try:
            supabase_store.write_audit("feedback_escalated", summary, feedback_id=feedback_id)
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=f"Feedback was identified, but the audit record could not be saved. {exc}") from None
    return {"feedback_id": feedback_id, "message": "Feedback marked for manual owner review. No customer response was sent automatically."}


@app.get("/api/inventory/movements")
def inventory_movements(_owner: dict = Depends(auth.require_owner)):
    if current_data_mode().startswith("supabase"):
        try:
            return {"movements": supabase_store.load_inventory_movements()}
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"movements": INVENTORY_MOVEMENTS[::-1]}


@app.post("/api/inventory/movements", status_code=201)
def create_inventory_movement(request: InventoryMovementSubmission, _owner: dict = Depends(auth.require_owner)):
    if current_data_mode().startswith("supabase"):
        try:
            movement = supabase_store.record_inventory_movement(request.model_dump())
        except KeyError:
            raise HTTPException(status_code=404, detail="Product inventory level not found.") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    else:
        product = next((item for item in PRODUCTS if item["id"] == request.product_id), None)
        if product is None:
            raise HTTPException(status_code=404, detail="Product inventory level not found.")
        delta = request.quantity if request.movement_type == "receipt" else -request.quantity
        if product["stock"] + delta < 0:
            raise HTTPException(status_code=422, detail="This write-off would make inventory negative.")
        product["stock"] += delta
        movement = {"id": str(uuid4()), "product_id": product["id"], "product_name": product["name"],
                    "movement_type": request.movement_type, "quantity": delta, "note": request.note,
                    "occurred_at": datetime.now(timezone.utc), "updated_stock": product["stock"]}
        INVENTORY_MOVEMENTS.append(movement)
    summary = f"Recorded {request.movement_type} of {request.quantity} units for inventory."
    AUDIT.append({"id": str(uuid4()), "event": "inventory_movement_recorded", "summary": summary,
                  "created_at": datetime.now(timezone.utc)})
    return {"movement": movement, "message": "Inventory movement recorded. This did not create a supplier order or customer transaction."}


@app.post("/api/customer/feedback", status_code=201)
def submit_feedback(request: FeedbackSubmission):
    if current_data_mode().startswith("supabase"):
        try:
            products, _ = supabase_store.load_business_data()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    else:
        products = PRODUCTS
    product = next((item for item in products if item["id"] == request.product_id), None)
    if product is None:
        raise HTTPException(status_code=422, detail="Select a product from the list.")

    safe_content, contact_was_masked = mask_contact_details(request.content)
    record = {
        "id": "F-" + uuid4().hex[:8].upper(),
        "product_id": product["id"],
        "category": request.category,
        "content": safe_content,
        "submitted_at": datetime.now(timezone.utc),
    }
    if current_data_mode().startswith("supabase"):
        try:
            record = supabase_store.create_feedback(record)
            supabase_store.write_audit(
                "customer_feedback_submitted",
                f"Customer submitted {request.category} feedback for {product['name']}; contact details masked before storage",
                feedback_id=record["id"],
            )
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=f"Feedback could not be saved to Supabase. {exc}") from None
    else:
        FEEDBACK.insert(0, record)
    AUDIT.append({
        "id": str(uuid4()), "event": "customer_feedback_submitted", "feedback_id": record["id"],
        "summary": f"Customer submitted {request.category} feedback for {product['name']}; contact details masked before storage",
        "created_at": datetime.now(timezone.utc),
    })
    return {
        "feedback": record,
        "contact_was_masked": contact_was_masked,
        "message": "Thank you. Your feedback was saved to Supabase." if current_data_mode().startswith("supabase") else "Thank you. Your feedback was saved to this local prototype.",
    }
