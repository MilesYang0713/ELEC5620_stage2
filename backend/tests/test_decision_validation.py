import unittest

from pydantic import ValidationError

from app.models import DecisionRequest


class DecisionValidationTests(unittest.TestCase):
    def test_rejection_requires_nonblank_reason(self):
        for note in ("", " \t\n "):
            with self.subTest(note=note), self.assertRaises(ValidationError):
                DecisionRequest(decision="reject", note=note)
        with self.assertRaises(ValidationError):
            DecisionRequest(decision="reject")

    def test_rejection_reason_is_trimmed(self):
        request = DecisionRequest(decision="reject", note="  Evidence is insufficient.  ")
        self.assertEqual(request.note, "Evidence is insufficient.")

    def test_approval_does_not_require_note(self):
        self.assertEqual(DecisionRequest(decision="approve").note, "")


if __name__ == "__main__":
    unittest.main()
