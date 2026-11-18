import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.assessments import (
    normalize_distribution,
    select_configured_questions,
)


def bank_question(difficulty, prompt):
    return SimpleNamespace(
        id=uuid4(),
        is_active=True,
        difficulty=difficulty,
        options=["first", "second"],
        question=prompt,
        correct_option="A",
        marks=1,
        category="python",
        topic="Python basics",
        subtopic=None,
        technology="Python",
        role="Python developer",
        explanation="",
    )


class ConfiguredQuestionSelectionTests(unittest.TestCase):
    def test_one_question_count_is_supported(self):
        self.assertEqual(
            normalize_distribution(
                {"easy": 100, "medium": 0, "hard": 0},
                1,
            ),
            {"easy": 1, "medium": 0, "hard": 0},
        )

    def test_manual_selection_returns_all_requested_questions(self):
        questions = [
            bank_question("easy", "Easy question"),
            bank_question("medium", "Medium question"),
            bank_question("hard", "Hard question"),
        ]
        selected_ids = [question.id for question in questions]

        selected, shortage = select_configured_questions(
            questions,
            total=3,
            distribution={"easy": 34, "medium": 33, "hard": 33},
            randomize=False,
            question_ids=selected_ids,
        )

        self.assertIsNone(shortage)
        self.assertEqual([item["bank_id"] for item in selected], selected_ids)

    def test_manual_selection_rejects_difficulty_mismatch(self):
        questions = [
            bank_question("easy", "First easy question"),
            bank_question("easy", "Second easy question"),
        ]

        with self.assertRaisesRegex(ValueError, "difficulty distribution"):
            select_configured_questions(
                questions,
                total=2,
                distribution={"easy": 50, "medium": 50, "hard": 0},
                randomize=False,
                question_ids=[question.id for question in questions],
            )


if __name__ == "__main__":
    unittest.main()
