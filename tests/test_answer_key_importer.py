from pathlib import Path

from services.answer_key_importer import build_answer_keys


def test_pdf_answer_key_import_builds_102_keys():
    keys = build_answer_keys(
        {
            1: Path(r"C:\Users\varun\Downloads\p1_provisional_keys.pdf"),
            2: Path(r"C:\Users\varun\Downloads\p2_provisional_keys.pdf"),
        }
    )

    assert len(keys) == 102
    assert {key.question_id for key in keys if key.paper == 1 and key.question_id == "2015963"}
    assert {key.question_id for key in keys if key.paper == 2 and key.question_id == "201596102"}
    assert any(key.answer_type == "numeric" and key.rule_json for key in keys)
    assert any(
        key.answer_type == "multiple"
        and key.full_marks == 4
        and key.negative_marks == -1
        and key.rule_json == {"partial_scheme": "jee_advanced_2026"}
        for key in keys
    )
    paper2_last = next(key for key in keys if key.paper == 2 and key.question_id == "201596102")
    assert paper2_last.answer_type == "numeric"
    assert paper2_last.full_marks == 4
    assert paper2_last.negative_marks == 0
    assert paper2_last.section == "Chem Sec 3"
