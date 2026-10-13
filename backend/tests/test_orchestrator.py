import unittest

from app.demo_data import FEEDBACK, PRODUCTS
from app.insights import feedback_insights, product_indicators
from app.orchestrator import run_demo


class DemoAnalysisTests(unittest.TestCase):
    def test_sales_analysis_includes_percentage_and_stock_cover(self):
        run = run_demo("Why are coffee sales falling?", "sales_decline")

        self.assertEqual(run.status, "completed")
        self.assertEqual(len(run.agents), 4)
        sales = next(agent for agent in run.agents if agent.agent == "Sales Agent")
        inventory = next(agent for agent in run.agents if agent.agent == "Inventory Agent")
        self.assertTrue(any("%" in item for item in sales.evidence))
        self.assertTrue(any("days of cover" in item for item in inventory.evidence))

    def test_controlled_failure_returns_partial_result(self):
        run = run_demo(
            "Analyse customer feedback and suggest improvements.",
            "feedback_analysis",
            products=PRODUCTS,
            feedback_records=FEEDBACK,
            simulated_failures={"Marketing Agent"},
        )

        self.assertEqual(run.status, "partial")
        marketing = next(agent for agent in run.agents if agent.agent == "Marketing Agent")
        self.assertEqual(marketing.status, "failed")
        self.assertTrue(any("unavailable agents" in item for item in run.limitations))

    def test_indicators_expose_stock_cover_and_feedback_themes(self):
        products = {item["product_id"]: item for item in product_indicators(PRODUCTS)}
        feedback = feedback_insights(FEEDBACK)

        self.assertEqual(products["P-003"]["risk"], "stock_out")
        self.assertIsNotNone(products["P-001"]["estimated_cover_days"])
        self.assertGreater(feedback["theme_counts"]["availability"], 0)


if __name__ == "__main__":
    unittest.main()
