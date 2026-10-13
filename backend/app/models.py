from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator

Workflow = Literal["sales_decline", "overstock", "demand_spike", "feedback_analysis"]
SpecialistName = Literal["Sales Agent", "Inventory Agent", "Pricing Agent", "Marketing Agent"]


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    workflow: Workflow | None = None
    product_id: str | None = Field(default=None, min_length=2, max_length=50)
    # This is deliberately a demonstration control: it makes resilience and partial
    # results observable without disconnecting a real model provider.
    simulate_failures: list[SpecialistName] = Field(default_factory=list, max_length=4)


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
    scope: dict[str, str] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class OwnerLogin(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def trim_email(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Enter an email address.")
        return trimmed


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


class FeedbackEscalation(BaseModel):
    note: str = Field(default="", max_length=500)


class InventoryMovementSubmission(BaseModel):
    product_id: str = Field(min_length=2, max_length=50)
    movement_type: Literal["receipt", "write_off"]
    quantity: int = Field(gt=0, le=100000)
    note: str = Field(default="", max_length=500)

    @field_validator("product_id", "note")
    @classmethod
    def trim_movement_text(cls, value: str) -> str:
        return value.strip()


class CustomerQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Enter a question.")
        return trimmed
