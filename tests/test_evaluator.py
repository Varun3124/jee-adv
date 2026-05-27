import pytest

from models import AnswerKey
from schemas import ParsedPaper, ParsedQuestion
from services.image_hash import ImageFingerprint
from services.evaluator import evaluate_question, evaluate_submission


def key(**overrides):
    data = {
        "paper": 1,
        "subject": "Physics",
        "section": "Phy Sec 1",
        "question_id": "q1",
        "answer_type": "single",
        "correct_answer": "A",
        "full_marks": 4,
        "partial_marks": 0,
        "negative_marks": 2,
    }
    data.update(overrides)
    return AnswerKey(**data)


def question(response="A", status="Answered"):
    return ParsedQuestion(
        paper=1,
        subject="Physics",
        section="Phy Sec 1",
        question_id="q1",
        status=status,
        response=response,
    )


@pytest.mark.asyncio
async def test_single_answer_correct_and_negative():
    assert (await evaluate_question(question("A"), key())).marks_awarded == 4
    wrong = await evaluate_question(question("B"), key())
    assert wrong.result == "incorrect"
    assert wrong.marks_awarded == -2


@pytest.mark.asyncio
async def test_single_answer_allows_multiple_acceptable_options():
    mcq_key = key(correct_answer=["A", "C"])
    slash_key = key(correct_answer="A/C")

    accepted = await evaluate_question(question("C"), mcq_key)
    slash_accepted = await evaluate_question(question("C"), slash_key)
    wrong = await evaluate_question(question("B"), mcq_key)

    assert accepted.result == "correct"
    assert accepted.marks_awarded == 4
    assert slash_accepted.result == "correct"
    assert wrong.result == "incorrect"


@pytest.mark.asyncio
async def test_unattempted_scores_zero():
    result = await evaluate_question(question(None, "Not Answered"), key())
    assert result.result == "unattempted"
    assert result.marks_awarded == 0


@pytest.mark.asyncio
async def test_multiple_answer_partial_subset():
    result = await evaluate_question(
        question("A,C"),
        key(answer_type="multiple", correct_answer=["A", "B", "C"], negative_marks=-1),
    )
    assert result.result == "partial"
    assert result.marks_awarded == 2


@pytest.mark.asyncio
async def test_msq_jee_advanced_partial_ladder_and_negative():
    msq_key = key(answer_type="multiple", correct_answer=["A", "B", "C", "D"], negative_marks=-1)

    three_of_four = await evaluate_question(question("A,B,C"), msq_key)
    two_correct = await evaluate_question(question("A,B"), msq_key)
    one_correct = await evaluate_question(question("A"), msq_key)
    wrong = await evaluate_question(question("A,B,E"), msq_key)

    assert three_of_four.marks_awarded == 3
    assert two_correct.marks_awarded == 2
    assert one_correct.marks_awarded == 1
    assert wrong.result == "incorrect"
    assert wrong.marks_awarded == -1


@pytest.mark.asyncio
async def test_msq_three_correct_options_gives_two_for_two_correct_choices():
    msq_key = key(answer_type="multiple", correct_answer=["A", "B", "C"], negative_marks=-1)

    two_correct = await evaluate_question(question("A,C"), msq_key)
    one_correct = await evaluate_question(question("A"), msq_key)
    too_few_for_two_mark_rule = await evaluate_question(question("A,B"), key(answer_type="multiple", correct_answer=["A", "B"], negative_marks=-1))

    assert two_correct.marks_awarded == 2
    assert one_correct.marks_awarded == 1
    assert too_few_for_two_mark_rule.result == "correct"


@pytest.mark.asyncio
async def test_numeric_tolerance():
    result = await evaluate_question(
        question("3.142"),
        key(answer_type="numeric", correct_answer="3.14", rule_json={"tolerance": 0.01}),
    )
    assert result.result == "correct"


@pytest.mark.asyncio
async def test_numeric_range_rule():
    result = await evaluate_question(
        question("1.47"),
        key(answer_type="numeric", correct_answer="1.45 to 1.50", rule_json={"min_value": 1.45, "max_value": 1.50}),
    )
    assert result.result == "correct"


@pytest.mark.asyncio
async def test_numeric_wrong_scores_zero():
    result = await evaluate_question(
        question("8"),
        key(answer_type="numeric", correct_answer="9", full_marks=4, negative_marks=0),
    )

    assert result.result == "incorrect"
    assert result.marks_awarded == 0


@pytest.mark.asyncio
async def test_submission_section_scores_allow_labels_and_missing_key_counts():
    paper = ParsedPaper(
        paper=1,
        source_url="x",
        questions=[question("A"), question(None, "Not Answered")],
    )
    result = await evaluate_submission([paper], {})
    section = result.section_scores["paper_1:Physics:Phy Sec 1"]
    assert section["subject"] == "Physics"
    assert section["missing_key"] == 1
    assert section["unattempted"] == 1


@pytest.mark.asyncio
async def test_image_hash_single_resolves_randomized_label_by_md5(monkeypatch):
    async def fake_fingerprint_urls(urls):
        return {
            "u-a": ImageFingerprint(md5="wrong-1", phash="ffffffffffffffff"),
            "u-b": ImageFingerprint(md5="correct", phash="0000000000000000"),
            "u-c": ImageFingerprint(md5="wrong-2", phash="ffffffffffffffff"),
            "u-d": ImageFingerprint(md5="wrong-3", phash="ffffffffffffffff"),
        }

    monkeypatch.setattr("services.evaluator.fingerprint_urls", fake_fingerprint_urls)
    result = await evaluate_question(
        image_question(response="B"),
        key(correct_answer={"mode": "image_hash", "count": 1}, correct_option_hash_md5="correct", correct_option_hash_phash="0000000000000000"),
    )

    assert result.result == "correct"
    assert result.marks_awarded == 4


@pytest.mark.asyncio
async def test_image_hash_single_falls_back_to_phash(monkeypatch):
    async def fake_fingerprint_urls(urls):
        return {
            "u-a": ImageFingerprint(md5="wrong-1", phash="ffffffffffffffff"),
            "u-b": ImageFingerprint(md5="wrong-2", phash="000000000000000f"),
            "u-c": ImageFingerprint(md5="wrong-3", phash="ffffffffffffffff"),
            "u-d": ImageFingerprint(md5="wrong-4", phash="ffffffffffffffff"),
        }

    monkeypatch.setattr("services.evaluator.fingerprint_urls", fake_fingerprint_urls)
    result = await evaluate_question(
        image_question(response="B"),
        key(correct_answer={"mode": "image_hash", "count": 1}, correct_option_hash_md5="correct", correct_option_hash_phash="0000000000000000"),
    )

    assert result.result == "correct"


@pytest.mark.asyncio
async def test_image_hash_ambiguous_phash_flags_manual_review(monkeypatch):
    async def fake_fingerprint_urls(urls):
        return {
            "u-a": ImageFingerprint(md5="wrong-1", phash="0000000000000001"),
            "u-b": ImageFingerprint(md5="wrong-2", phash="0000000000000002"),
            "u-c": ImageFingerprint(md5="wrong-3", phash="ffffffffffffffff"),
            "u-d": ImageFingerprint(md5="wrong-4", phash="ffffffffffffffff"),
        }

    monkeypatch.setattr("services.evaluator.fingerprint_urls", fake_fingerprint_urls)
    result = await evaluate_question(
        image_question(response="A"),
        key(correct_answer={"mode": "image_hash", "count": 1}, correct_option_hash_md5="correct", correct_option_hash_phash="0000000000000000"),
    )

    assert result.result == "manual_review"
    assert result.marks_awarded == 0


@pytest.mark.asyncio
async def test_image_hash_multiple_scores_resolved_label_set(monkeypatch):
    async def fake_fingerprint_urls(urls):
        return {
            "u-a": ImageFingerprint(md5="correct-1", phash="0000000000000000"),
            "u-b": ImageFingerprint(md5="wrong-1", phash="ffffffffffffffff"),
            "u-c": ImageFingerprint(md5="correct-2", phash="00000000000000ff"),
            "u-d": ImageFingerprint(md5="wrong-2", phash="ffffffffffffffff"),
        }

    monkeypatch.setattr("services.evaluator.fingerprint_urls", fake_fingerprint_urls)
    msq_key = key(
        answer_type="multiple",
        correct_answer={"mode": "image_hash", "count": 2},
        correct_option_hash_md5=["correct-1", "correct-2"],
        correct_option_hash_phash=["0000000000000000", "00000000000000ff"],
        negative_marks=-1,
    )

    correct = await evaluate_question(image_question(response="A,C"), msq_key)
    partial = await evaluate_question(image_question(response="A"), msq_key)
    incorrect = await evaluate_question(image_question(response="A,B"), msq_key)

    assert correct.result == "correct"
    assert partial.result == "partial"
    assert partial.marks_awarded == 1
    assert incorrect.result == "incorrect"


@pytest.mark.asyncio
async def test_image_hash_missing_option_urls_flags_manual_review():
    result = await evaluate_question(
        question("A"),
        key(correct_answer={"mode": "image_hash", "count": 1}, correct_option_hash_md5="correct", correct_option_hash_phash="0000000000000000"),
    )

    assert result.result == "manual_review"


def image_question(response="A"):
    return ParsedQuestion(
        paper=1,
        subject="Physics",
        section="Phy Sec 1",
        question_id="q1",
        question_type="MCQ",
        status="Answered",
        response=response,
        option_image_urls={"A": "u-a", "B": "u-b", "C": "u-c", "D": "u-d"},
    )
