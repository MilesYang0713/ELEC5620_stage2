import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.llm_client import LLMRequestError
from app.orchestrator import _parse_manager, _parse_specialist, run_llm


class LLMOutputValidationTests(unittest.TestCase):
    def setUp(self):
        self.facts = [
            "Harbour Blend Coffee has 12 units in stock.",
            "Harbour Blend Coffee sold 4 units in the last 7 days.",
        ]

    def test_specialist_keeps_only_exact_fact_evidence(self):
        parsed = _parse_specialist(
            "Inventory Agent",
            '{"summary":"Stock is available for review.",'
            '"evidence":["Harbour Blend Coffee has 12 units in stock.",'
            '"The supplier will deliver tomorrow."],"limitations":[]}',
            self.facts,
        )

        self.assertEqual(parsed["evidence"], [self.facts[0]])
        self.assertEqual(parsed["status"], "completed")

    def test_specialist_rejects_missing_required_fields(self):
        invalid_outputs = [
            '{"evidence":[],"limitations":[]}',
            '{"summary":"Stock reviewed.","limitations":[]}',
            '{"summary":"Stock reviewed.","evidence":[],"limitations":"none"}',
        ]

        for raw in invalid_outputs:
            with self.subTest(raw=raw):
                with self.assertRaises(LLMRequestError):
                    _parse_specialist("Inventory Agent", raw, self.facts)

    def test_specialist_rejects_response_with_only_unsupported_evidence(self):
        raw = (
            '{"summary":"Stock is low.","evidence":["Only 2 units remain."],'
            '"limitations":[]}'
        )

        with self.assertRaises(LLMRequestError):
            _parse_specialist("Inventory Agent", raw, self.facts)

    def test_manager_filters_unsupported_evidence(self):
        raw = (
            '{"title":"Review stock","action":"Review the stock position.",'
            '"priority":"medium","evidence":["Harbour Blend Coffee has 12 units in stock.",'
            '"Supplier delivery is guaranteed tomorrow."],"confidence":"Low"}'
        )

        parsed = _parse_manager(raw, self.facts)

        self.assertEqual(parsed["evidence"], [self.facts[0]])

    def test_manager_rejects_missing_fields_invalid_priority_or_ungrounded_evidence(self):
        invalid_outputs = [
            '{"title":"Review stock","action":"Review it.","priority":"medium",'
            '"evidence":[],"confidence":"Low"}',
            '{"title":"Review stock","action":"Review it.","priority":"urgent",'
            '"evidence":["Harbour Blend Coffee has 12 units in stock."],"confidence":"Low"}',
            '{"title":"Review stock","action":"Review it.","priority":"medium",'
            '"evidence":["Supplier delivery is guaranteed tomorrow."],"confidence":"Low"}',
        ]

        for raw in invalid_outputs:
            with self.subTest(raw=raw):
                with self.assertRaises(LLMRequestError):
                    _parse_manager(raw, self.facts)

    def test_invalid_manager_output_returns_conservative_partial_result(self):
        specialist_results = {
            name: {
                "status": "completed",
                "summary": "Reviewed the supplied facts.",
                "evidence": [self.facts[0]],
                "limitations": [],
            }
            for name in ("Sales Agent", "Inventory Agent", "Pricing Agent", "Marketing Agent")
        }
        execution = SimpleNamespace(
            specialist_results=specialist_results,
            specialist_errors=[],
            manager_output=(
                '{"title":"Clear stock","action":"Apply a 90% discount now.",'
                '"priority":"high","evidence":["A fabricated fact."],"confidence":"High"}'
            ),
            manager_error=False,
        )

        with patch("app.orchestrator.run_retail_analysis_flow", return_value=execution):
            result = run_llm("Review overstock", workflow="overstock")

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.recommendations[0].title, "Review slow-moving stock")
        self.assertTrue(any("conservative fallback" in item for item in result.limitations))

    def test_valid_manager_output_completes_with_grounded_recommendation(self):
        specialist_results = {
            name: {
                "status": "completed",
                "summary": "Reviewed the supplied facts.",
                "evidence": [self.facts[0]],
                "limitations": [],
            }
            for name in ("Sales Agent", "Inventory Agent", "Pricing Agent", "Marketing Agent")
        }
        execution = SimpleNamespace(
            specialist_results=specialist_results,
            specialist_errors=[],
            manager_output=(
                '{"title":"Review stock","action":"Review the stock position before changing it.",'
                '"priority":"medium","evidence":["Harbour Blend Coffee has 12 units in stock."],'
                '"confidence":"Low, based on seeded records."}'
            ),
            manager_error=False,
        )

        with patch("app.orchestrator.run_retail_analysis_flow", return_value=execution) as flow_call:
            result = run_llm("Review overstock", workflow="overstock")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.recommendations[0].evidence, [self.facts[0]])
        self.assertTrue(flow_call.call_args.kwargs["analysis_id"])


if __name__ == "__main__":
    unittest.main()
