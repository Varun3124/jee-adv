from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from schemas import ParsedPaper, ParsedQuestion


SECTION_RE = re.compile(
    r'(?is)Section\s*:\s*(?:&nbsp;)?</span>\s*<span[^>]*class=["\']bold["\'][^>]*>(?P<section>[^<]+)'
)
QUESTION_RE = re.compile(
    r"(?is)Question ID\s*:</td>\s*<td[^>]*class=[\"']bold[\"'][^>]*>(?P<qid>[^<]+)</td>"
    r".*?Status\s*:</td>\s*<td[^>]*class=[\"']bold[\"'][^>]*>(?P<status>[^<]+)</td>"
    r"(?P<body>.*?)</table>\s*</td>\s*</tr>"
)
CHOSEN_RE = re.compile(
    r"(?is)Chosen Option\s*:</td>\s*<td[^>]*class=[\"']bold[\"'][^>]*>(?P<chosen>[^<]+)</td>"
)


class ParserError(ValueError):
    pass


async def fetch_response_sheet(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def parse_response_sheet(html: str, source_url: str, paper: int) -> ParsedPaper:
    soup = BeautifulSoup(html, "html.parser")
    candidate_id = _metadata_value(soup, "Candidate ID")
    candidate_name = _metadata_value(soup, "Candidate Name")

    questions: list[ParsedQuestion] = []
    for section_container in soup.select(".section-cntnr"):
        section_label = section_container.select_one(".section-lbl .bold")
        section = _clean_text(section_label.get_text(" ")) if section_label else "Unknown"
        for panel in section_container.select(".question-pnl"):
            question_id = _panel_value(panel, "Question ID")
            if not question_id:
                continue
            chosen = _panel_value(panel, "Chosen Option")
            given_answer = _panel_value(panel, "Given Answer")
            questions.append(
                ParsedQuestion(
                    paper=paper,
                    subject=_subject_from_section(section),
                    section=section,
                    question_id=question_id,
                    question_type=_panel_value(panel, "Question Type"),
                    status=_panel_value(panel, "Status"),
                    response=chosen or given_answer or None,
                    option_image_urls=_option_image_urls(panel, source_url),
                )
            )

    if not questions:
        questions = _parse_response_sheet_with_regex(html, source_url, paper)

    if not questions:
        raise ParserError("No DigiAlm question blocks were found in the response sheet.")

    return ParsedPaper(
        paper=paper,
        candidate_id=candidate_id,
        candidate_name=candidate_name,
        source_url=source_url,
        questions=questions,
    )


def _parse_response_sheet_with_regex(html: str, source_url: str, paper: int) -> list[ParsedQuestion]:
    sections = [(match.start(), _clean_text(match.group("section"))) for match in SECTION_RE.finditer(html)]
    questions: list[ParsedQuestion] = []
    current_section = ""
    section_index = 0
    for match in QUESTION_RE.finditer(html):
        while section_index < len(sections) and sections[section_index][0] < match.start():
            current_section = sections[section_index][1]
            section_index += 1
        chosen_match = CHOSEN_RE.search(match.group("body"))
        chosen = _clean_text(chosen_match.group("chosen")) if chosen_match else None
        section = current_section or "Unknown"
        questions.append(
            ParsedQuestion(
                paper=paper,
                subject=_subject_from_section(section),
                section=section,
                question_id=_clean_text(match.group("qid")),
                status=_clean_text(match.group("status")),
                response=chosen,
                option_image_urls={},
            )
        )
    return questions


def _metadata_value(soup: BeautifulSoup, label: str) -> str | None:
    cells = soup.find_all("td")
    for index, cell in enumerate(cells[:-1]):
        if _clean_text(cell.get_text(" ")) == label:
            return _clean_text(cells[index + 1].get_text(" "))
    return None


def _panel_value(panel, label: str) -> str:
    normalized_label = label.rstrip(":").strip().lower()
    cells = panel.find_all("td")
    for index, cell in enumerate(cells[:-1]):
        text = _clean_text(cell.get_text(" ")).rstrip(":").strip().lower()
        if text == normalized_label:
            return _clean_text(cells[index + 1].get_text(" "))
    return ""


def _option_image_urls(panel, source_url: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for image in panel.find_all("img"):
        label = _option_label_for_image(image)
        src = image.get("src")
        if label and src and label not in urls:
            urls[label] = urljoin(source_url, src)
    return urls


def _option_label_for_image(image) -> str | None:
    node = image.parent
    while node is not None and getattr(node, "name", None) != "tr":
        text = _clean_text(node.get_text(" "))
        match = re.match(r"^([A-D])\.", text)
        if match:
            return match.group(1)
        node = node.parent
    if node is not None:
        text = _clean_text(node.get_text(" "))
        match = re.match(r"^([A-D])\.", text)
        if match:
            return match.group(1)
    return None


def _subject_from_section(section: str) -> str:
    prefix = section.strip().split(" ", 1)[0].lower()
    return {
        "math": "Mathematics",
        "phy": "Physics",
        "physics": "Physics",
        "chem": "Chemistry",
        "chemistry": "Chemistry",
    }.get(prefix, "Unknown")


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()
