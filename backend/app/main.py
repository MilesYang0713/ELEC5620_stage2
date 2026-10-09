import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .demo_data import FEEDBACK, PRODUCTS
from .llm_client import LLMConfigurationError, LLMRequestError
from .models import AnalysisRun, AnalyzeRequest, DecisionRequest
from .orchestrator import LLMAnalysisError, run_demo, run_llm

app = FastAPI(title="SoloRetail AI API", version="0.2.0", description="Retail analysis prototype with demo and DashScope-compatible LLM modes")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:4173"], allow_methods=["*"], allow_headers=["*"])
RUNS: dict[str, AnalysisRun] = {}
AUDIT: list[dict] = []


def current_data_mode() -> str:
    return os.getenv("DATA_MODE", "demo").strip().lower()


def llm_configured() -> bool:
    return all(os.getenv(name, "").strip() for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"))


@app.get("/health")
def health():
    mode = current_data_mode()
    return {"status": "ok", "data_mode": mode, "llm_configured": llm_configured() if mode == "llm" else False}


@app.get("/api/dashboard")
def dashboard():
    return {"data_mode": current_data_mode(), "as_of": datetime.now(timezone.utc), "products": PRODUCTS, "feedback_count": len(FEEDBACK), "runs": list(RUNS.values())[-5:], "audit": AUDIT[-10:]}


@app.post("/api/analyze", response_model=AnalysisRun)
def analyze(request: AnalyzeRequest):
    mode = current_data_mode()
    if mode == "llm":
        try:
            run = run_llm(request.question, request.workflow)
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except LLMAnalysisError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        except LLMRequestError:
            raise HTTPException(status_code=502, detail="The configured model provider could not return a valid response.") from None
    elif mode == "demo":
        run = run_demo(request.question, request.workflow)
    else:
        raise HTTPException(status_code=503, detail="DATA_MODE must be either 'demo' or 'llm'.")

    RUNS[run.id] = run
    summary_mode = "LLM-assisted analysis using seeded demo records" if run.data_mode == "llm" else "demo mode"
    AUDIT.append({"id": str(uuid4()), "event": "analysis_created", "run_id": run.id, "summary": f"Started {run.workflow} analysis in {summary_mode}", "created_at": datetime.now(timezone.utc)})
    return run


@app.get("/api/analyses", response_model=list[AnalysisRun])
def analyses():
    return list(RUNS.values())[::-1]


@app.post("/api/recommendations/{recommendation_id}/decision")
def decide(recommendation_id: str, request: DecisionRequest):
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
    return {"data_mode": current_data_mode(), "products": PRODUCTS}


@app.get("/api/customer/feedback")
def feedback():
    return {"data_mode": current_data_mode(), "feedback": FEEDBACK}
