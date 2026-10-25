import asyncio
import json
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_crewai_test_stubs():
    """Provide only the CrewAI import surface needed by these isolated flow tests."""
    crewai = types.ModuleType("crewai")
    crewai.Agent = object
    crewai.LLM = object
    flow_package = types.ModuleType("crewai.flow")
    flow_module = types.ModuleType("crewai.flow.flow")

    class Flow:
        def __init__(self):
            self.state = None

        def __class_getitem__(cls, _item):
            return cls

    def start():
        return lambda function: function

    def listen(_event):
        return lambda function: function

    flow_module.Flow = Flow
    flow_module.start = start
    flow_module.listen = listen
    crewai.flow = flow_package
    sys.modules["crewai"] = crewai
    sys.modules["crewai.flow"] = flow_package
    sys.modules["crewai.flow.flow"] = flow_module


_install_crewai_test_stubs()

from app import crewai_flow


class FailingAgent:
    def __init__(self, error):
        self.error = error

    async def kickoff_async(self, _prompt):
        raise self.error


class SequencedAgent:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def kickoff_async(self, _prompt):
        self.calls += 1
        result = next(self.outcomes)
        if isinstance(result, Exception):
            raise result
        return result


class CrewAIFlowDiagnosticTests(unittest.TestCase):
    def _logged_event(self, operation):
        with self.assertLogs("app.llm_diagnostics", level="WARNING") as captured:
            operation()
        return json.loads(captured.output[0].split(":", 2)[2])

    def test_specialist_request_failure_logs_run_and_agent_without_exception_text(self):
        error = TimeoutError("provider secret and user prompt")
        flow = crewai_flow.RetailAnalysisFlow(
            llm=object(),
            manager_system="manager instructions",
            parse_specialist=lambda *_args: {},
        )
        flow.state = crewai_flow.RetailAnalysisState(
            analysis_id="run-456",
            workflow="overstock",
            question="private user prompt",
            agent_tasks={"Inventory Agent": "review stock"},
        )

        with patch.object(crewai_flow, "Agent", return_value=FailingAgent(error)):
            event = self._logged_event(lambda: asyncio.run(flow.analyze_with_specialists()))

        self.assertEqual(event["analysis_id"], "run-456")
        self.assertEqual(event["agent_name"], "Inventory Agent")
        self.assertEqual(event["error_type"], "TimeoutError")
        self.assertEqual(event["error_category"], "timeout")
        self.assertNotIn("provider secret", json.dumps(event))
        self.assertNotIn("private user prompt", json.dumps(event))

    def test_manager_request_failure_is_logged_as_manager_agent(self):
        flow = crewai_flow.RetailAnalysisFlow(
            llm=object(),
            manager_system="manager instructions",
            parse_specialist=lambda *_args: {},
        )
        flow.state = crewai_flow.RetailAnalysisState(
            analysis_id="run-789",
            workflow="overstock",
            question="review overstock",
            facts=["Product has 8 units in stock."],
            specialist_results={
                "Inventory Agent": {
                    "status": "completed",
                    "summary": "Stock was reviewed.",
                    "evidence": ["Product has 8 units in stock."],
                    "limitations": [],
                },
            },
        )

        with patch.object(
            crewai_flow,
            "Agent",
            return_value=FailingAgent(ConnectionError("provider private details")),
        ):
            event = self._logged_event(
                lambda: asyncio.run(flow.synthesize_with_manager({"completed": ["Inventory Agent"]}))
            )

        self.assertEqual(event["analysis_id"], "run-789")
        self.assertEqual(event["agent_name"], "Manager Agent")
        self.assertEqual(event["error_type"], "ConnectionError")
        self.assertEqual(event["error_category"], "connection")
        self.assertNotIn("provider private details", json.dumps(event))

    def test_analysis_id_is_carried_into_flow_state(self):
        class CapturingFlow:
            def __init__(self, **_kwargs):
                self.state = SimpleNamespace()

            async def kickoff_async(self, inputs):
                self.state = SimpleNamespace(**inputs)

        environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_MODEL": "test-model",
        }
        with patch.dict(os.environ, environment), patch.object(crewai_flow, "LLM"), patch.object(
            crewai_flow, "RetailAnalysisFlow", CapturingFlow
        ):
            state = crewai_flow.run_retail_analysis_flow(
                analysis_id="run-abc",
                question="review stock",
                workflow="overstock",
                facts=[],
                agent_tasks={},
                manager_system="manager instructions",
                parse_specialist=lambda *_args: {},
            )

        self.assertEqual(state.analysis_id, "run-abc")

    def test_transient_specialist_failure_retries_once_and_recovers(self):
        agent = SequencedAgent([
            TimeoutError("private provider details"),
            SimpleNamespace(raw="valid response"),
        ])
        flow = crewai_flow.RetailAnalysisFlow(
            llm=object(), manager_system="manager instructions",
            parse_specialist=lambda _name, _raw, _facts: {
                "status": "completed", "summary": "Recovered", "evidence": [], "limitations": [],
            },
        )
        flow.state = crewai_flow.RetailAnalysisState(
            analysis_id="run-retry", workflow="overstock", question="review stock",
            agent_tasks={"Inventory Agent": "review stock"},
        )
        with patch.object(crewai_flow, "Agent", return_value=agent), patch.object(
            crewai_flow.asyncio, "sleep", new_callable=lambda: _no_delay
        ), self.assertLogs("app.llm_diagnostics", level="WARNING") as captured:
            asyncio.run(flow.analyze_with_specialists())
        self.assertEqual(agent.calls, 2)
        self.assertEqual(flow.state.specialist_results["Inventory Agent"]["status"], "completed")
        self.assertEqual(flow.state.specialist_errors, [])
        event = json.loads(captured.output[0].split(":", 2)[2])
        self.assertEqual((event["attempt"], event["retrying"], event["error_category"]), (1, True, "timeout"))
        self.assertNotIn("private provider details", json.dumps(event))
        recovered = json.loads(captured.output[1].split(":", 2)[2])
        self.assertEqual((recovered["event"], recovered["attempt"]), ("llm_agent_request_recovered", 2))

    def test_auth_failure_is_not_retried(self):
        class AuthenticationError(Exception):
            pass

        agent = SequencedAgent([AuthenticationError("private provider details")])
        with self.assertLogs("app.llm_diagnostics", level="WARNING") as captured:
            with self.assertRaises(AuthenticationError):
                asyncio.run(crewai_flow._kickoff_with_retry(
                    agent, "private prompt", analysis_id="run-auth", agent_name="Manager Agent",
                ))
        self.assertEqual(agent.calls, 1)
        event = json.loads(captured.output[0].split(":", 2)[2])
        self.assertEqual((event["attempt"], event["retrying"], event["error_category"]), (1, False, "authentication"))

    def test_manager_request_recovers_after_connection_failure(self):
        agent = SequencedAgent([ConnectionError("private"), SimpleNamespace(raw='{"title":"Review"}')])
        flow = crewai_flow.RetailAnalysisFlow(
            llm=object(), manager_system="manager instructions", parse_specialist=lambda *_args: {},
        )
        flow.state = crewai_flow.RetailAnalysisState(
            analysis_id="run-manager-retry", workflow="overstock", question="review stock",
            specialist_results={"Inventory Agent": {
                "status": "completed", "summary": "Stock reviewed", "evidence": ["8 units"], "limitations": [],
            }},
        )
        with patch.object(crewai_flow, "Agent", return_value=agent), patch.object(
            crewai_flow.asyncio, "sleep", new_callable=lambda: _no_delay
        ), self.assertLogs("app.llm_diagnostics", level="WARNING"):
            asyncio.run(flow.synthesize_with_manager({"completed": ["Inventory Agent"]}))
        self.assertEqual(agent.calls, 2)
        self.assertFalse(flow.state.manager_error)
        self.assertEqual(flow.state.manager_output, '{"title":"Review"}')

    def test_rate_limit_retries_once_then_stops(self):
        class RateLimitError(Exception):
            pass

        agent = SequencedAgent([RateLimitError("private"), RateLimitError("private")])
        with patch.object(crewai_flow.asyncio, "sleep", new_callable=lambda: _no_delay), self.assertLogs(
            "app.llm_diagnostics", level="WARNING"
        ) as captured:
            with self.assertRaises(RateLimitError):
                asyncio.run(crewai_flow._kickoff_with_retry(
                    agent, "prompt", analysis_id="run-limit", agent_name="Pricing Agent",
                ))
        self.assertEqual(agent.calls, 2)
        events = [json.loads(line.split(":", 2)[2]) for line in captured.output]
        self.assertEqual([event["retrying"] for event in events], [True, False])
        self.assertEqual([event["error_category"] for event in events], ["rate_limit", "rate_limit"])


async def _no_delay(_seconds):
    pass


if __name__ == "__main__":
    unittest.main()
