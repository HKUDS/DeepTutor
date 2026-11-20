"""Standalone chart tabs must not prevent extraction of worksheet cells."""

import base64
import io

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart
from openpyxl.chart.data_source import NumData, NumDataSource, NumVal
from openpyxl.chart.series import Series
import pytest

from deeptutor.utils import document_extractor

EXPECTED_TEXT = (
    "--- Sheet: Scores ---\nLearner\tScore\nAda\t97\n\n--- Sheet: Notes ---\nExam\tPractice"
)


def _workbook_bytes(*, charts: bool = True, worksheets: bool = True) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    if worksheets:
        scores = workbook.create_sheet("Scores")
        scores.append(["Learner", "Score"])
        scores.append(["Ada", 97])
        notes = workbook.create_sheet("Notes")
        notes.append(["Exam", "Practice"])
        notes.sheet_state = "hidden"
    if charts:
        for index, name in enumerate(("Before", "Between", "After")):
            chart = BarChart()
            # Literal values keep the chart-only workbook independent of cell references.
            chart.series.append(
                Series(val=NumDataSource(numLit=NumData(ptCount=1, pt=[NumVal(idx=0, v=97)])))
            )
            sheet = workbook.create_chartsheet(name, index=index * 2 if worksheets else index)
            sheet.add_chart(chart)
    buffer = io.BytesIO()
    try:
        workbook.save(buffer)
    finally:
        workbook.close()
    return buffer.getvalue()


@pytest.mark.parametrize("fallback", [False, True], ids=["openpyxl", "ooxml"])
@pytest.mark.parametrize("charts", [False, True], ids=["worksheets", "interleaved-charts"])
def test_worksheet_text_and_order_survive_chart_tabs(
    monkeypatch: pytest.MonkeyPatch, fallback: bool, charts: bool
) -> None:
    data = _workbook_bytes(charts=charts)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        assert workbook.sheetnames == (
            ["Before", "Scores", "Between", "Notes", "After"] if charts else ["Scores", "Notes"]
        )
        assert [list(sheet.values) for sheet in workbook.worksheets] == [
            [("Learner", "Score"), ("Ada", 97)],
            [("Exam", "Practice")],
        ]
        assert workbook["Notes"].sheet_state == "hidden"
    finally:
        workbook.close()
    monkeypatch.setattr(document_extractor, "load_workbook", None if fallback else load_workbook)

    assert document_extractor.extract_text_from_bytes("scores.xlsx", data) == EXPECTED_TEXT


@pytest.mark.parametrize("fallback", [False, True], ids=["openpyxl", "ooxml"])
def test_chart_only_workbook_reports_no_extractable_text(
    monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    data = _workbook_bytes(worksheets=False)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        assert workbook.worksheets == []
        assert len(workbook.chartsheets) == 3
    finally:
        workbook.close()
    monkeypatch.setattr(document_extractor, "load_workbook", None if fallback else load_workbook)

    with pytest.raises(document_extractor.EmptyDocumentError, match="no extractable text"):
        document_extractor.extract_text_from_bytes("charts.xlsx", data)


def test_chart_tabs_do_not_abort_chat_attachment_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_extractor, "load_workbook", load_workbook)
    record = {
        "type": "file",
        "filename": "scores.xlsx",
        "base64": base64.b64encode(_workbook_bytes()).decode("ascii"),
    }

    texts, records = document_extractor.extract_documents_from_records([record])

    assert texts == [f"[File: scores.xlsx]\n{EXPECTED_TEXT}"]
    assert records[0]["extracted_text"] == EXPECTED_TEXT
    assert records[0]["base64"] == ""
