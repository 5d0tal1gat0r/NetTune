"""The real server, over a real socket: one slow client must not stop the rest.

September 30: a client fetching the sheet images one by one over Tailscale
held the single-threaded HTTPServer, and every other request -- the
colleague's included -- waited more than thirty seconds. Requests now each
get a thread for their socket; the page work itself still runs one at a
time (dashboard._dispatch_lock), so the store is never used concurrently.
"""

import socket
import threading
import time
import urllib.request

import pytest

from nettune.report.entry_store import EntryStore
from nettune.review.dashboard import make_server


@pytest.fixture
def server(tmp_path):
    with EntryStore(str(tmp_path / "e.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", "Intervenciones Seguridad:",
                  [{"text": "Se retiran pelonas.", "confident": False}],
                  "s.pdf", "01-09-2026 p1")
        # Built in this thread, the one that owns the store -- as main does.
        httpd = make_server(0, store, host="127.0.0.1")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield httpd
        httpd.shutdown()
        httpd.server_close()


def _get(httpd, path):
    host, port = httpd.server_address[:2]
    request = urllib.request.Request(f"http://{host}:{port}{path}",
                                     headers={"Host": f"127.0.0.1:{port}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read().decode()


def test_a_request_is_served_from_a_worker_thread(server):
    status, body = _get(server, "/mes/2026/SEPTIEMBRE")
    assert status == 200
    assert "Se retiran pelonas." in body


def test_a_stalled_client_does_not_block_the_next(server):
    host, port = server.server_address[:2]
    stalled = socket.create_connection((host, port))
    try:
        # Promises a body it never sends: the server sits in rfile.read.
        stalled.sendall(b"POST /guardar/2026/SEPTIEMBRE HTTP/1.1\r\n"
                        b"Host: 127.0.0.1\r\nContent-Length: 1000\r\n\r\n")
        time.sleep(0.2)
        started = time.monotonic()
        status, _ = _get(server, "/mes/2026/SEPTIEMBRE")
        assert status == 200
        assert time.monotonic() - started < 3
    finally:
        stalled.close()


def test_a_dead_connection_is_let_go(server):
    handler = server.RequestHandlerClass
    assert 0 < handler.timeout <= 60, "a socket that never finishes frees its thread"
