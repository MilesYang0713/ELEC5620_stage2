import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .demo_data import FEEDBACK, PRODUCTS
from .llm_client import LLMConfigurationError, LLMRequestError
from .models import AnalysisRun, AnalyzeRequest, CustomerQuestion, DecisionRequest, FeedbackSubmission
from .orchestrator import LLMAnalysisError, run_demo, run_llm
from . import supabase_store
from .customer_qa import answer_customer_question

app = FastAPI(title="SoloRetail AI API", version="0.2.0", description="Retail analysis prototype with demo and DashScope-compatible LLM modes")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:4173"], allow_methods=["*"], allow_headers=["*"])
RUNS: dict[str, AnalysisRun] = {}
AUDIT: list[dict] = []
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


@app.get("/health")
def health():
    mode = current_data_mode()
    return {"status": "ok", "data_mode": mode,
            "llm_configured": llm_configured() if mode in ("llm", "supabase_llm") else False,
            "supabase_configured": supabase_store.configured()}


@app.get("/api/dashboard")
def dashboard():
    mode = current_data_mode()
    if mode.startswith("supabase"):
        try:
            products, feedback_records = supabase_store.load_business_data()
            runs = supabase_store.load_runs(limit=5)
            audit = supabase_store.load_audit(limit=10)
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return {"data_mode": mode, "as_of": datetime.now(timezone.utc), "products": products,
                "feedback_count": len(feedback_records), "feedback": feedback_records,
                "runs": runs, "audit": audit}
    return {"data_mode": current_data_mode(), "as_of": datetime.now(timezone.utc), "products": PRODUCTS, "feedback_count": len(FEEDBACK), "feedback": FEEDBACK, "runs": list(RUNS.values())[-5:], "audit": AUDIT[-10:]}


@app.post("/api/analyze", response_model=AnalysisRun)
def analyze(request: AnalyzeRequest):
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
    if use_llm:
        try:
            run = run_llm(request.question, request.workflow, products=products, feedback_records=feedback_records,
                          data_mode="supabase_llm" if use_supabase else "llm")
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except LLMAnalysisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        except LLMRequestError:
            raise HTTPException(status_code=502, detail="The configured model provider could not return a valid response.") from None
    elif mode in ("demo", "supabase"):
        run = run_demo(request.question, request.workflow, products=products, feedback_records=feedback_records,
                       data_mode="supabase" if use_supabase else "demo")
    else:
        raise HTTPException(status_code=503, detail="DATA_MODE must be demo, llm, supabase, or supabase_llm.")

    RUNS[run.id] = run
    summary_mode = "LLM-assisted analysis using seeded demo records" if run.data_mode == "llm" else "demo mode"
    AUDIT.append({"id": str(uuid4()), "event": "analysis_created", "run_id": run.id, "summary": f"Started {run.workflow} analysis in {summary_mode}", "created_at": datetime.now(timezone.utc)})
    if use_supabase:
        try:
            supabase_store.save_run(run, audit_summary=f"Started {run.workflow} analysis in {run.data_mode} mode")
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=f"Analysis completed, but its database record could not be fully saved. {exc}") from None
    return run


@app.get("/api/analyses", response_model=list[AnalysisRun])
def analyses():
    if current_data_mode().startswith("supabase"):
        try:
            return supabase_store.load_runs()
        except supabase_store.SupabaseError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
    return list(RUNS.values())[::-1]


@app.post("/api/recommendations/{recommendation_id}/decision")
def decide(recommendation_id: str, request: DecisionRequest):
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
