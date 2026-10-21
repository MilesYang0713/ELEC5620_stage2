"""CrewAI Flow for bounded, parallel retail analysis and manager synthesis."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Callable

# This prototype does not need CrewAI telemetry. Set the opt-out before import.
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

from crewai import Agent, LLM
from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field

from .diagnostics import log_agent_failure
from .llm_client import LLMConfigurationError, LLMRequestError


class RetailAnalysisState(BaseModel):
    analysis_id: str = ""
    question: str = ""
    workflow: str = ""
    facts: list[str] = Field(default_factory=list)
    agent_tasks: dict[str, str] = Field(default_factory=dict)
    specialist_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    specialist_errors: list[str] = Field(default_factory=list)
    manager_output: str | None = None
    manager_error: bool = False


class RetailAnalysisFlow(Flow[RetailAnalysisState]):
    """Run specialist agents concurrently, validate their evidence, then synthesize."""

    def __init__(self, llm: LLM, manager_system: str,
                 parse_specialist: Callable[[str, str, list[str]], dict[str, Any]]):
        super().__init__()
        self._llm = llm
        self._manager_system = manager_system
        self._parse_specialist = parse_specialist

    @start()
    async def analyze_with_specialists(self) -> dict[str, Any]:
        state = self.state
        agents = {
            name: Agent(
                role=name,
                goal=task,
                backstory=(
                    f"You are the {name} for a small independent retailer. Use only supplied business facts. "
                    "Never invent data, external events, causes, or calculations. Return one JSON object with "
                    "string 'summary', array 'evidence' copied exactly from the supplied facts, and array 'limitations'. "
                    "Keep it concise and state uncertainty."
                ),
                llm=self._llm,
                tools=[],
                allow_delegation=False,
                max_iter=1,
                max_retry_limit=0,
                max_execution_time=75,
                verbose=False,
            )
            for name, task in state.agent_tasks.items()
        }

        user_prompt = (
            f"Workflow: {state.workflow}\n"
            f"Store owner question: {state.question}\n"
            "Available business facts:\n"
            + "\n".join(f"- {fact}" for fact in state.facts)
        )

        async def run_one(name: str, agent: Agent) -> tuple[str, dict[str, Any]]:
            try:
                response = await agent.kickoff_async(user_prompt)
            except Exception as exc:
                log_agent_failure(
                    analysis_id=state.analysis_id,
                    agent_name=name,
                    error=exc,
                )
                return name, _failed_agent_result()

            try:
                raw = getattr(response, "raw", None)
                if not isinstance(raw, str) or not raw.strip():
                    raise LLMRequestError("The model returned an empty response.")
                parsed = self._parse_specialist(name, raw.strip(), state.facts)
                parsed["completed_at"] = datetime.now(timezone.utc)
                return name, parsed
            except Exception as exc:
                log_agent_failure(
                    analysis_id=state.analysis_id,
                    agent_name=name,
                    error=exc,
                    error_category="invalid_response",
                )
                return name, _failed_agent_result()

        results = await asyncio.gather(*(run_one(name, agent) for name, agent in agents.items()))
        for name, result in results:
            state.specialist_results[name] = result
            if result["status"] == "failed":
                state.specialist_errors.append(name)
        return {"completed": list(state.specialist_results), "failed": state.specialist_errors}

    @listen(analyze_with_specialists)
    async def synthesize_with_manager(self, _specialists: dict[str, Any]) -> str | None:
        state = self.state
        available = {
            name: {key: result[key] for key in ("summary", "evidence", "limitations")}
            for name, result in state.specialist_results.items()
            if result.get("status") == "completed"
        }
        if not available:
            state.manager_error = True
            return None

        evidence_pool = list(dict.fromkeys(
            evidence
            for result in available.values()
            for evidence in result["evidence"]
        ))
        user_prompt = (
            "Integrate the specialist results into one cautious recommendation. Use only the supplied facts and "
            "validated specialist evidence. Return a JSON object with string 'title', string 'action', "
            "'priority' (high/medium/low), array 'evidence' copied exactly from 'evidence_pool', and string 'confidence'.\n\n"
            f"Workflow: {state.workflow}\n"
            f"Store owner question: {state.question}\n"
            f"Available facts: {state.facts}\n"
            f"Specialist results: {available}\n"
            f"Evidence pool: {evidence_pool}"
        )
        agent = Agent(
            role="Manager Agent",
            goal="Integrate specialist findings into one cautious, evidence-led retail recommendation.",
            backstory=(
                "You coordinate a small independent retailer's Sales, Inventory, Pricing, and Marketing specialists. "
                "Recommendations are advisory. Never claim an action was executed or invent missing business data."
            ),
            llm=self._llm,
            tools=[],
            allow_delegation=False,
            max_iter=1,
            max_retry_limit=0,
            max_execution_time=75,
            verbose=False,
        )
        try:
            response = await agent.kickoff_async(self._manager_system + "\n\n" + user_prompt)
        except Exception as exc:
            log_agent_failure(
                analysis_id=state.analysis_id,
                agent_name="Manager Agent",
                error=exc,
            )
            state.manager_error = True
            return None

        try:
            raw = getattr(response, "raw", None)
            if not isinstance(raw, str) or not raw.strip():
                raise LLMRequestError("The model returned an empty response.")
            state.manager_output = raw.strip()
            return state.manager_output
        except Exception as exc:
            log_agent_failure(
                analysis_id=state.analysis_id,
                agent_name="Manager Agent",
                error=exc,
                error_category="invalid_response",
            )
            state.manager_error = True
            return None


def _failed_agent_result() -> dict[str, Any]:
    """Return the same safe partial result for any specialist failure."""
    return {
        "status": "failed",
        "summary": "This agent could not return a valid result.",
        "evidence": [],
        "limitations": ["Model response unavailable or invalid; no result was inferred."],
        "completed_at": datetime.now(timezone.utc),
    }


def run_retail_analysis_flow(
    *,
    analysis_id: str,
    question: str,
    workflow: str,
    facts: list[str],
    agent_tasks: dict[str, str],
    manager_system: str,
    parse_specialist: Callable[[str, str, list[str]], dict[str, Any]],
) -> RetailAnalysisState:
    """Run the CrewAI Flow synchronously from the existing FastAPI route."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("OPENAI_MODEL", "").strip()
    missing = [
        name for name, value in (
            ("OPENAI_API_KEY", api_key),
            ("OPENAI_BASE_URL", base_url),
            ("OPENAI_MODEL", model),
        ) if not value
    ]
    if missing:
        error = LLMConfigurationError("Missing required model configuration: " + ", ".join(missing))
        log_agent_failure(
            analysis_id=analysis_id,
            agent_name="analysis_flow",
            error=error,
            error_category="configuration",
        )
        raise error

    try:
        llm = LLM(
            model=f"openai/{model}",
            custom_openai=True,
            base_url=base_url,
            api_key=api_key,
            temperature=0.2,
            timeout=75,
            max_retries=0,
        )
        flow = RetailAnalysisFlow(llm=llm, manager_system=manager_system, parse_specialist=parse_specialist)
        asyncio.run(flow.kickoff_async(inputs={
            "analysis_id": analysis_id,
            "question": question,
            "workflow": workflow,
            "facts": facts,
            "agent_tasks": agent_tasks,
        }))
        return flow.state
    except LLMConfigurationError as exc:
        log_agent_failure(
            analysis_id=analysis_id,
            agent_name="analysis_flow",
            error=exc,
            error_category="configuration",
        )
        raise
    except Exception as exc:
        log_agent_failure(
            analysis_id=analysis_id,
            agent_name="analysis_flow",
            error=exc,
        )
        raise LLMRequestError("The CrewAI analysis flow could not complete.") from None
