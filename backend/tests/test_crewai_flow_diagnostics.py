import asyncio
import importlib.util
import json
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_crewai_test_stubs():
    """Provide only the CrewAI import surface needed by these isolated flow tests."""
    if importlib.util.find_spec("crewai") is not None:
        return

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


if __name__ == "__main__":
    unittest.main()
