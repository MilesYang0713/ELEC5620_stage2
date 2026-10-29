import unittest

from app.models import DecisionRequest


class DecisionValidationTests(unittest.TestCase):
    def test_rejection_reason_is_optional(self):
        self.assertEqual(DecisionRequest(decision="reject").note, "")
        self.assertEqual(DecisionRequest(decision="reject", note=" \t\n ").note, "")

    def test_rejection_reason_is_trimmed(self):
        request = DecisionRequest(decision="reject", note="  Evidence is insufficient.  ")
        self.assertEqual(request.note, "Evidence is insufficient.")

    def test_approval_does_not_require_note(self):
        self.assertEqual(DecisionRequest(decision="approve").note, "")


if __name__ == "__main__":
    unittest.main()
