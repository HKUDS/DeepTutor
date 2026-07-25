from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import httpx

from deeptutor.update import HttpReleaseProvider, Installation, InstallMode


class _PyPIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        payload = json.dumps(
            {"releases": {"1.5.4": [{"yanked": False}], "1.6.0": [{"yanked": False}]}}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def test_pypi_lookup_crosses_a_real_http_boundary() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PyPIHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = HttpReleaseProvider(
            client=httpx.Client(),
            pypi_url=f"http://127.0.0.1:{server.server_port}/pypi/deeptutor/json",
        )

        release = provider.latest(
            Installation(
                mode=InstallMode.PYPI,
                current_version="1.5.4",
                package_name="deeptutor",
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert release.version == "1.6.0"
