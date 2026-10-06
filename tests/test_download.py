"""ionis-download: resume and retry (#14), progress off a terminal (#15), sizes (#16)."""

import email.message
import io
import urllib.error

import pytest

from ionis_mcp import download as dl
from ionis_mcp.download import SQLITE_MAGIC

BODY = SQLITE_MAGIC + bytes(range(256)) * 1024  # a 256 KiB "database"
URL = "https://master.dl.sourceforge.net/x"


def headers(**h) -> email.message.Message:
    m = email.message.Message()
    for k, v in h.items():
        m[k.replace("_", "-")] = str(v)
    return m


class Response:
    """An HTTP response; with cut_at, the connection drops after that many bytes."""

    def __init__(self, body, status=200, hdrs=None, url=URL, cut_at=None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = hdrs or headers(Content_Type="application/octet-stream", Content_Length=len(body))
        self._url = url
        self._left = cut_at

    def geturl(self):
        return self._url

    def read(self, n):
        if self._left is not None:
            if self._left <= 0:
                raise ConnectionResetError("connection reset by peer")
            n = min(n, self._left)
            self._left -= n
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Server:
    """SourceForge, answering Range requests; script lists what each request gets."""

    def __init__(self, *script):
        self.script = list(script)
        self.ranges = []

    def __call__(self, req):
        rng = req.get_header("Range")
        self.ranges.append(rng)
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, Exception):
            raise step
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        cut = step if isinstance(step, int) else None
        if rng and step != "ignore-range":
            body = BODY[start:]
            return Response(body, 206, headers(
                Content_Type="application/octet-stream", Content_Length=len(body),
                Content_Range=f"bytes {start}-{len(BODY) - 1}/{len(BODY)}"), cut_at=cut)
        return Response(BODY, cut_at=cut)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setitem(dl.DATASETS, "test", ("t", "test.sqlite", "test", len(BODY)))
    monkeypatch.setattr(dl, "CHUNK", 16 * 1024)
    sleeps = []

    def go(server, force=False):
        monkeypatch.setattr(dl, "_open", server)
        return dl.download_dataset("test", str(tmp_path), force=force, sleep=sleeps.append)

    go.dest = tmp_path / "t" / "test.sqlite"
    go.part = tmp_path / "t" / "test.sqlite.part"
    go.sleeps = sleeps
    return go


def test_a_clean_download(run):
    assert run(Server("ok"))
    assert run.dest.read_bytes() == BODY and not run.part.exists()


def test_a_dropped_connection_resumes_where_it_stopped(run):
    server = Server(100_000, "ok")  # drops after 100,000 bytes, then serves the rest
    assert run(server)
    assert server.ranges == [None, "bytes=100000-"]  # every byte that arrived was kept
    assert run.dest.read_bytes() == BODY
    assert run.sleeps == [dl.BACKOFF_SECONDS]


def test_transient_errors_are_retried_with_backoff(run):
    server = Server(TimeoutError("timed out"),
                    urllib.error.HTTPError(URL, 503, "busy", headers(), None), "ok")
    assert run(server)
    assert run.sleeps == [dl.BACKOFF_SECONDS, dl.BACKOFF_SECONDS * 2]


def test_giving_up_keeps_the_partial_file_to_resume_next_time(run, capsys):
    assert not run(Server(*([50_000] * dl.RETRIES)))
    assert run.part.exists() and not run.dest.exists()
    assert "run the same command again to resume" in capsys.readouterr().out
    server = Server("ok")
    assert run(server)  # the next run picks up from the partial file
    assert server.ranges[0].startswith("bytes=") and run.dest.read_bytes() == BODY


def test_a_server_that_ignores_range_starts_over(run):
    run.part.parent.mkdir(parents=True)
    run.part.write_bytes(b"x" * 1000)
    assert run(Server("ignore-range"))
    assert run.dest.read_bytes() == BODY


def test_a_whole_partial_file_is_checked_not_downloaded_again(run):
    run.part.parent.mkdir(parents=True)
    run.part.write_bytes(BODY)
    done = urllib.error.HTTPError(URL, 416, "range", headers(Content_Range=f"bytes */{len(BODY)}"), None)
    assert run(Server(done))
    assert run.dest.read_bytes() == BODY


def test_a_permanent_error_is_not_retried(run):
    assert not run(Server(urllib.error.HTTPError(URL, 404, "gone", headers(), None)))
    assert run.sleeps == [] and not run.part.exists()


def test_an_error_page_is_not_retried_or_kept(run):
    page = Response(b"<html>" + b"x" * 80_000, hdrs=headers(Content_Type="text/html", Content_Length=80_006))
    assert not run(lambda req: page)
    assert run.sleeps == [] and not run.part.exists() and not run.dest.exists()


def test_a_redirect_off_https_is_refused(run):
    assert not run(lambda req: Response(BODY, url="http://mirror.example/x"))
    assert not run.dest.exists()


def test_force_discards_a_partial_file(run):
    run.part.parent.mkdir(parents=True)
    run.part.write_bytes(b"x" * 1000)
    server = Server("ok")
    assert run(server, force=True)
    assert server.ranges == [None] and run.dest.read_bytes() == BODY


# ── #15 progress ─────────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_progress_off_a_terminal_is_a_line_every_ten_percent():
    out, clock = io.StringIO(), Clock()
    p = dl.Progress(1000, tty=False, out=out, clock=clock)
    for _ in range(1000):
        p.update(1)
    lines = out.getvalue().splitlines()
    assert len(lines) == 10 and "\r" not in out.getvalue()
    assert lines[-1].strip().startswith("100.0%")
    assert lines[-1].strip() == "100.0%  0.0 MB of 0.0 MB"  # 1,000 bytes


def test_progress_off_a_terminal_also_reports_every_thirty_seconds():
    out, clock = io.StringIO(), Clock()
    p = dl.Progress(1000, tty=False, out=out, clock=clock)
    p.update(1)
    clock.t = 31
    p.update(1)
    assert len(out.getvalue().splitlines()) == 1


def test_progress_on_a_terminal_rewrites_one_line_at_most_twice_a_second():
    out, clock = io.StringIO(), Clock()
    p = dl.Progress(1000, tty=True, out=out, clock=clock)
    for i in range(1000):
        clock.t = i * 0.01  # 10 seconds in all
        p.update(1)
    writes = out.getvalue().count("\r")
    assert 15 <= writes <= 21 and "\n" not in out.getvalue()


# ── #16 sizes ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("size,text", [
    (9_059_115_008, "9.1 GB"), (444_567_552, "445 MB"), (8_024_064, "8.0 MB"),
    (1_118_208, "1.1 MB"), (118_784, "0.1 MB"),
])
def test_sizes_are_decimal_and_labelled(size, text):
    assert dl._format_size(size) == text


def test_bundle_sizes_add_up():
    assert dl._format_size(dl._bundle_size("minimal")) == "454 MB"
    assert dl._format_size(dl._bundle_size("full")) == "16.2 GB"
