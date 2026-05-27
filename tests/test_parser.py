from pathlib import Path

from services.parser import parse_response_sheet


FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_extracts_paper1_candidate_sections_and_questions():
    html = (FIXTURES / "paper1_sample.html").read_text(encoding="utf-8")
    parsed = parse_response_sheet(html, "https://example.test/paper1.html", paper=1)

    assert parsed.candidate_id == "262109373"
    assert parsed.candidate_name == "KABEER CHHILLAR"
    assert len(parsed.questions) == 48
    assert parsed.questions[0].question_id == "2015963"
    assert parsed.questions[0].subject == "Mathematics"
    assert parsed.questions[0].section == "Math Sec 1"
    assert parsed.questions[0].response == "C"
    assert parsed.questions[0].question_type == "MCQ"
    assert set(parsed.questions[0].option_image_urls) == {"A", "B", "C", "D"}
    assert parsed.questions[0].option_image_urls["A"].startswith("https://example.test/per/")


def test_parser_extracts_paper2_question_count():
    html = (FIXTURES / "paper2_sample.html").read_text(encoding="utf-8")
    parsed = parse_response_sheet(html, "https://example.test/paper2.html", paper=2)

    assert parsed.paper == 2
    assert len(parsed.questions) == 54
    assert parsed.questions[0].question_id == "20159651"
    assert parsed.questions[0].response == "A"
