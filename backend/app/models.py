from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

Workflow = Literal["sales_decline", "overstock", "demand_spike", "feedback_analysis"]


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    workflow: Workflow | None = None


class AgentResult(BaseModel):
    agent: str
    status: Literal["completed", "partial", "failed", "running"]
    summary: str
    evidence: list[str] = []
    limitations: list[str] = []
    completed_at: datetime


class Recommendation(BaseModel):
    id: str
    title: str
    priority: Literal["high", "medium", "low"]
    action: str
    evidence: list[str]
    confidence: str
    high_risk: bool
    status: Literal["pending_approval", "approved", "rejected", "advisory"]
    approval_note: str


class AnalysisRun(BaseModel):
    id: str
    question: str
    workflow: Workflow
    status: Literal["completed", "partial", "failed"]
    data_mode: Literal["demo", "llm", "supabase", "supabase_llm"]
    created_at: datetime
    agents: list[AgentResult]
    recommendations: list[Recommendation]
    limitations: list[str]


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)



class FeedbackSubmission(BaseModel):
    product_id: str = Field(min_length=2, max_length=20)
    category: Literal["product", "service", "complaint"]
    content: str = Field(min_length=5, max_length=2000)

    @field_validator("product_id", "content")
    @classmethod
    def trim_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field cannot be blank.")
        return trimmed


class CustomerQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Enter a question.")
        return trimmed
