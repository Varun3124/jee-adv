from schemas import EvaluationResult, ParsedPaper, ParsedQuestion
from services.submissions import _deduplicate_question_results, _deduplicate_questions, hash_submission


def test_submission_hash_is_stable_for_question_order():
    paper_a = ParsedPaper(
        paper=1,
        source_url="a",
        questions=[
            ParsedQuestion(paper=1, subject="Physics", section="S", question_id="2", response="B"),
            ParsedQuestion(paper=1, subject="Physics", section="S", question_id="1", response="A"),
        ],
    )
    paper_b = ParsedPaper(
        paper=1,
        source_url="a",
        questions=[
            ParsedQuestion(paper=1, subject="Physics", section="S", question_id="1", response="A"),
            ParsedQuestion(paper=1, subject="Physics", section="S", question_id="2", response="B"),
        ],
    )

    assert hash_submission([paper_a]) == hash_submission([paper_b])


def test_submission_hash_ignores_duplicate_question_entries():
    canonical = ParsedPaper(
        paper=1,
        source_url="a",
        questions=[
            ParsedQuestion(paper=1, subject="Mathematics", section="S", question_id="2015963", status="Answered", response="C"),
        ],
    )
    with_duplicate = ParsedPaper(
        paper=1,
        source_url="a",
        questions=[
            ParsedQuestion(paper=1, subject="Mathematics", section="S", question_id="2015963", status="Not Answered", response=None),
            ParsedQuestion(paper=1, subject="Mathematics", section="S", question_id="2015963", status="Answered", response="C"),
        ],
    )

    assert hash_submission([canonical]) == hash_submission([with_duplicate])


def test_question_dedup_prefers_attempted_over_unattempted_duplicate():
    paper = ParsedPaper(
        paper=1,
        source_url="a",
        questions=[
            ParsedQuestion(paper=1, subject="Mathematics", section="S", question_id="2015963", status="Not Answered", response=None),
            ParsedQuestion(paper=1, subject="Mathematics", section="S", question_id="2015963", status="Answered", response="C"),
        ],
    )

    deduped = _deduplicate_questions(paper)
    assert len(deduped.questions) == 1
    assert deduped.questions[0].response == "C"


def test_result_dedup_prefers_higher_quality_result():
    results = [
        EvaluationResult(
            paper=1,
            subject="Mathematics",
            section="S",
            question_id="2015963",
            status="Not Answered",
            student_response=None,
            correct_answer=None,
            result="unattempted",
            marks_awarded=0,
            max_marks=3,
        ),
        EvaluationResult(
            paper=1,
            subject="Mathematics",
            section="S",
            question_id="2015963",
            status="Answered",
            student_response="C",
            correct_answer="C",
            result="correct",
            marks_awarded=3,
            max_marks=3,
        ),
    ]

    deduped = _deduplicate_question_results(results)
    assert len(deduped) == 1
    assert deduped[0].result == "correct"
