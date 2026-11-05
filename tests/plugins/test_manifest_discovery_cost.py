from pathlib import Path

from deeptutor.plugins.registry import _manifest_files


def test_non_plugin_wheel_does_not_materialize_its_file_inventory():
    class Distribution:
        def read_text(self, name):
            assert name == "RECORD"
            return "package/code.py,sha256=abc,123\npackage-1.dist-info/METADATA,,\n"

        @property
        def files(self):
            raise AssertionError("No manifest: should not parse the file inventory")

    assert _manifest_files(Distribution()) == []


def test_manifest_candidate_and_legacy_distribution_still_use_authoritative_files(tmp_path):
    path = tmp_path / "deeptutor.plugin.json"
    path.write_text('{"id":"example"}')

    class Distribution:
        files = [Path("deeptutor.plugin.json")]

        def read_text(self, name):
            return self.record

        def locate_file(self, item):
            return tmp_path / item

    for record in [None, "pkg/DEEPTUTOR.PLUGIN.JSON,sha256=abc,123\n"]:
        dist = Distribution()
        dist.record = record
        assert _manifest_files(dist) == [(path, {"id": "example"}, "")]
