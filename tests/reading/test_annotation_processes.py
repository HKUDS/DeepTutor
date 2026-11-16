"""Annotation read/compare/write must serialize across independent workers."""

from __future__ import annotations

from contextlib import contextmanager
import multiprocessing
from pathlib import Path
from queue import Empty

import pytest

from deeptutor.reading import Annotation, ReadingStore
from deeptutor.reading.models import AnnotationConflict


class PausingStore(ReadingStore):
    """Hold a real write after its read so another worker can try to enter."""

    def __init__(self, root, entered, release):
        super().__init__(root)
        self.entered = entered
        self.release = release

    def _write_annotations(self, material_id, rows):
        self.entered.set()
        if not self.release.wait(15):
            raise TimeoutError("test did not release the first writer")
        super()._write_annotations(material_id, rows)


def _save_worker(root, material, payload, result, entered=None, release=None):
    store = PausingStore(root, entered, release) if entered is not None else ReadingStore(root)
    try:
        row = store.save_annotation(material, Annotation.from_dict(payload))
        result.put(("saved", row.annotation_id, row.note))
    except AnnotationConflict:
        result.put(("conflict",))
    except Exception as error:
        result.put(("error", repr(error)))


@contextmanager
def _workers():
    context = multiprocessing.get_context("spawn")
    processes = []
    try:
        yield context, processes
    finally:
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def _material(tmp_path: Path):
    store = ReadingStore(tmp_path / "reading")
    material = "aabbccddeeff0011"
    store.ingest_units(
        material, filename="notes.txt", units=["alpha beta"], unit="section", render_mode="text"
    )
    return store, material


@pytest.mark.parametrize("same_annotation", [True, False], ids=["stale-edit", "distinct-creates"])
def test_annotation_writes_are_serialized_between_processes(tmp_path, same_annotation):
    store, material = _material(tmp_path)
    if same_annotation:
        original = store.save_annotation(
            material, Annotation(annotation_id="", locator=1, note="old")
        )
        first = {**original.to_dict(), "note": "first", "expected_updated_at": original.updated_at}
        second = {**first, "note": "second"}
    else:
        first = {"annotation_id": "", "locator": 1, "note": "first"}
        second = {**first, "note": "second"}

    with _workers() as (context, processes):
        entered, release, attempted = context.Event(), context.Event(), context.Event()
        first_result, second_result = context.Queue(), context.Queue()
        writer = context.Process(
            target=_save_worker,
            args=(store.root, material, first, first_result, entered, release),
        )
        processes.append(writer)
        writer.start()
        try:
            assert entered.wait(15), "first worker did not reach the write"
            contender = context.Process(
                target=_attempt_save_worker,
                args=(store.root, material, second, second_result, attempted),
            )
            processes.append(contender)
            contender.start()
            assert attempted.wait(15), "second worker did not attempt the save"
            with pytest.raises(Empty):
                second_result.get(timeout=0.3)
        finally:
            release.set()
        assert first_result.get(timeout=15)[0] == "saved"
        outcome = second_result.get(timeout=15)
        assert outcome[0] == ("conflict" if same_annotation else "saved"), outcome
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0

    notes = sorted(row.note for row in store.annotations(material))
    assert notes == (["first"] if same_annotation else ["first", "second"])


def _attempt_save_worker(root, material, payload, result, attempted):
    attempted.set()
    _save_worker(root, material, payload, result)
