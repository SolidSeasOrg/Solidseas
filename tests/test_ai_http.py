"""The HTTP layer against a fake server on 127.0.0.1: timeouts, cancellation, 429 back-off,
401, size caps, proxies, pinned addresses, TLS context and the base-URL rules. No test
reaches a network (``netguard``)."""

import json
import socket
import sys
import threading
import time
import types

import pytest

from ai_support import Drip, FakeProxy, FakeServer, Reply, Stall
from solidseas.ai import http as aihttp
from solidseas.ai.errors import (
    CancelledError,
    NetworkError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    UnauthorizedError,
    UnavailableError,
)
from solidseas.ai.http import Cancel, HttpClient, parse_endpoint, retry_after_seconds


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


def client(server, **kw) -> HttpClient:
    kw.setdefault("backoff_base", 0.01)
    return HttpClient(server.url, **kw)


# --------------------------------------------------------------------------- requests
def test_a_post_round_trip(server):
    server.script.append(Reply(200, {"ok": True}))
    reply = client(server).send("POST", "/v1/x", headers={"x-test": "1"}, body=b'{"a":1}')
    assert reply.status == 200 and reply.json() == {"ok": True}
    seen = server.seen[0]
    assert (seen.method, seen.path, seen.body) == ("POST", "/v1/x", b'{"a":1}')
    assert seen.headers["x-test"] == "1" and seen.headers["content-type"] == "application/json"
    assert seen.headers["user-agent"] == "SolidSeas"


def test_the_base_path_is_kept(server):
    server.script.append(Reply(200, {}))
    HttpClient(server.url + "/ollama/").send("GET", "/api/tags")
    assert server.seen[0].path == "/ollama/api/tags"


def test_a_reply_that_is_not_json_or_holds_nan_is_refused(server):
    server.script += [Reply(200, b"<html>"), Reply(200, b'{"a": NaN}')]
    c = client(server)
    for _ in range(2):
        with pytest.raises(ProviderError):
            c.send("GET", "/").json()


# --------------------------------------------------------------------------- statuses
@pytest.mark.parametrize("status", [401, 403])
def test_401_and_403_stop_at_once(server, status):
    server.script.append(Reply(status, {"error": {"message": "Incorrect API key provided: sk-abc...xyz9"}}))
    with pytest.raises(UnauthorizedError) as info:
        client(server).send("POST", "/v1/x", body=b"{}")
    assert len(server.seen) == 1, "never retried"
    assert "sk-" not in str(info.value) and "Incorrect" not in str(info.value), "a 401 body is never quoted"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_never_followed(server, status):
    other = FakeServer()
    try:
        other.script.append(Reply(200, {"ok": True}))
        server.script.append(Reply(status, {}, {"Location": other.url + "/v1/x"}))
        with pytest.raises(ProviderError) as info:
            client(server).send("POST", "/v1/x", headers={"x-api-key": "sk-test-123456"}, body=b"{}")
        assert f"status {status}" in str(info.value)
        assert len(server.seen) == 1, "never retried"
        assert other.seen == [], "the key never goes where a reply points"
    finally:
        other.close()


def test_429_honours_retry_after_and_then_succeeds(server):
    server.script += [
        Reply(429, {}, {"Retry-After": "0"}),
        Reply(429, {}, {"Retry-After": "0"}),
        Reply(200, {"ok": 1}),
    ]
    assert client(server).send("POST", "/", body=b"{}").json() == {"ok": 1}
    assert len(server.seen) == 3


def test_429_gives_up_after_a_few_tries(server):
    server.default = Reply(429, {"error": {"message": "rate limited"}})
    with pytest.raises(RateLimitedError):
        client(server).send("POST", "/", body=b"{}")
    assert len(server.seen) == aihttp.MAX_TRIES


def test_a_long_retry_after_is_not_waited_out(server):
    server.default = Reply(429, {}, {"Retry-After": "120"})
    start = time.monotonic()
    with pytest.raises(RateLimitedError):
        client(server).send("POST", "/", body=b"{}")
    assert len(server.seen) == 1 and time.monotonic() - start < 5


def test_retries_stop_before_the_deadline(server):
    server.default = Reply(429, {}, {"Retry-After": "2"})
    with pytest.raises(RateLimitedError):
        client(server).send("POST", "/", body=b"{}", deadline=time.monotonic() + 1)
    assert len(server.seen) == 1


@pytest.mark.parametrize("status", [503, 529])
def test_overloaded_is_retried_then_reported(server, status):
    server.default = Reply(status, {})
    with pytest.raises(UnavailableError) as info:
        client(server).send("POST", "/", body=b"{}")
    assert len(server.seen) == aihttp.MAX_TRIES and str(status) in str(info.value)


def test_other_errors_quote_the_provider_message_scrubbed(server):
    server.script.append(
        Reply(400, {"error": {"message": "model nope not found; key sk-live-abcdef123456 bad\x1b"}})
    )
    c = client(server, scrub=lambda t: t.replace("sk-live-abcdef123456", "[key]"))
    with pytest.raises(ProviderError) as info:
        c.send("POST", "/", body=b"{}")
    text = str(info.value)
    assert "status 400" in text and "model nope not found" in text and "[key]" in text
    assert "sk-live" not in text and "\x1b" not in text
    assert len(server.seen) == 1


def test_the_provider_message_is_scrubbed_whole_before_it_is_cut():
    secret = "SECRETKEY0123456789"
    message = "x" * 190 + " key " + secret

    def scrub(text):
        return text.replace(secret, "[key]")

    body = json.dumps({"error": {"message": message}}).encode()
    shown = aihttp.error_excerpt(body, scrub)
    assert len(shown) <= 200 and "SECR" not in shown, "the cut would have left SECR for the scrub to miss"
    assert aihttp.error_excerpt(json.dumps({"error": {"message": "y" * 20_001}}).encode(), scrub) is None


def test_a_reply_larger_than_the_cap_is_refused(server, monkeypatch):
    monkeypatch.setattr(aihttp, "MAX_RESPONSE_BYTES", 1000)
    server.script.append(Reply(200, b"x" * 5000))
    with pytest.raises(ProviderError) as info:
        client(server).send("GET", "/")
    assert "larger" in str(info.value)


def test_a_client_that_downloads_files_sets_its_own_cap(server, monkeypatch):
    monkeypatch.setattr(aihttp, "MAX_RESPONSE_BYTES", 1000)
    server.script += [Reply(200, b"x" * 5000), Reply(200, b"x" * 9000)]
    files = client(server, max_response_bytes=8000)
    assert len(files.send("GET", "/bin.stl").body) == 5000
    with pytest.raises(ProviderError, match="larger"):
        files.send("GET", "/bin.stl")


# --------------------------------------------------------------------------- time and cancellation
def test_a_server_that_never_answers_times_out(server):
    server.script.append(Stall())
    start = time.monotonic()
    with pytest.raises(ProviderTimeoutError) as info:
        client(server, read_timeout=0.5).send("POST", "/", body=b"{}")
    assert time.monotonic() - start < 5
    assert info.value.delivered, "the server had the request, so the provider may bill for it"


def test_a_trickling_reply_cannot_hold_the_call_open(server):
    server.script.append(Drip(length=1000, every=0.1))
    start = time.monotonic()
    with pytest.raises(ProviderTimeoutError):
        client(server, read_timeout=0.8, connect_timeout=0.5).send("GET", "/")
    assert time.monotonic() - start < 5, "the whole reply had to arrive within the read timeout"


def test_the_deadline_bounds_the_call(server):
    server.script.append(Stall())
    start = time.monotonic()
    with pytest.raises(ProviderTimeoutError):
        client(server).send("POST", "/", body=b"{}", deadline=time.monotonic() + 0.5)
    assert time.monotonic() - start < 5
    with pytest.raises(ProviderTimeoutError):
        client(server).send("POST", "/", body=b"{}", deadline=time.monotonic() - 1)
    assert len(server.seen) == 1, "a passed deadline sends nothing"


def test_stop_cancels_a_call_in_flight_at_once(server):
    server.script.append(Stall())
    cancel = Cancel()
    threading.Timer(0.3, cancel.cancel).start()
    start = time.monotonic()
    with pytest.raises(CancelledError) as info:
        client(server).send("POST", "/", body=b"{}", cancel=cancel)
    assert time.monotonic() - start < 3
    assert info.value.delivered


def test_stop_cancels_a_back_off_wait(server):
    server.default = Reply(429, {}, {"Retry-After": "20"})
    cancel = Cancel()
    threading.Timer(0.3, cancel.cancel).start()
    start = time.monotonic()
    with pytest.raises((CancelledError, RateLimitedError)):
        client(server, backoff_base=10).send("POST", "/", body=b"{}", cancel=cancel)
    assert time.monotonic() - start < 3
    server.default = Reply(429, {})
    cancel = Cancel()
    threading.Timer(0.3, cancel.cancel).start()
    with pytest.raises(CancelledError):
        client(server, backoff_base=5).send("POST", "/", body=b"{}", cancel=cancel)


def test_a_cancelled_token_sends_nothing(server):
    cancel = Cancel()
    cancel.cancel()
    with pytest.raises(CancelledError):
        client(server).send("GET", "/", cancel=cancel)
    assert server.seen == []


def test_cancel_hooks():
    c = Cancel()
    ran = []
    hook = c.on_cancel(lambda: ran.append(1))
    c.remove(hook)
    c.on_cancel(lambda: ran.append(2))
    c.cancel()
    assert ran == [2] and c.cancelled and c.wait(5)
    assert c.on_cancel(lambda: ran.append(3)) is None and ran == [2, 3]


def test_retry_after_parsing():
    assert retry_after_seconds("3") == 3.0
    assert retry_after_seconds("-3") == 0.0
    assert retry_after_seconds(None) is None and retry_after_seconds("soon") is None
    assert retry_after_seconds("nan") is None
    when = "Wed, 21 Oct 2015 07:28:10 GMT"
    assert retry_after_seconds(when, now=1445412480.0) == pytest.approx(10.0)


# --------------------------------------------------------------------------- reaching the server
def test_a_refused_connection_names_the_host_and_the_proxy_limits():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(NetworkError) as info:
        HttpClient(f"http://127.0.0.1:{port}").send("GET", "/")
    assert f"127.0.0.1:{port}" in str(info.value) and "PAC" in str(info.value)
    assert not info.value.delivered, "nothing was sent"


@pytest.mark.parametrize(
    "url, words",
    [
        ("ftp://x.example", "http"),
        ("https://user:pw@api.example.test", "user name"),
        ("https://api.example.test/v1?key=sk-123", "query"),
        ("https://api.example.test/#frag", "fragment"),
        ("http://api.example.test", "this machine"),
        ("http://192.0.2.5:11434", "this machine"),
        ("https://api.example.test:99999", "port"),
        ("https://", "no host"),
        ("", "empty"),
        ("https://api.example.test/ x", "spaces"),
    ],
)
def test_base_urls_are_checked(url, words):
    with pytest.raises(ValueError) as info:
        parse_endpoint(url)
    assert words in str(info.value)
    assert "sk-123" not in str(info.value) and "pw" not in str(info.value)


def test_plain_http_is_for_loopback_or_a_listed_host():
    assert parse_endpoint("http://localhost:11434").is_loopback
    assert parse_endpoint("http://[::1]:11434").host == "::1"
    assert parse_endpoint("http://127.0.0.2").port == 80
    assert parse_endpoint("http://ollama.lab:11434", plain_http_hosts=("ollama.lab",)).host == "ollama.lab"
    e = parse_endpoint("https://API.Example.Test./v1/")
    assert (e.host, e.port, e.path, e.display()) == (
        "api.example.test",
        443,
        "/v1",
        "https://api.example.test",
    )


def test_localhost_is_pinned_to_a_loopback_address(server, monkeypatch):
    c = HttpClient(f"http://localhost:{server.port}", pin=True, use_proxies=False)
    server.script.append(Reply(200, {"ok": 1}))
    assert c.send("GET", "/").json() == {"ok": 1}
    assert server.seen[0].headers["host"] == f"localhost:{server.port}"

    def lying(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", 1)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", lying)
    with pytest.raises(NetworkError) as info:
        c.send("GET", "/")
    assert "not this machine" in str(info.value)
    assert len(server.seen) == 1


def test_a_pinned_client_connects_to_the_address_it_resolved(server, monkeypatch):
    resolved = []

    def to_loopback(host, port, *args, **kwargs):
        resolved.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", to_loopback)
    c = HttpClient(
        f"http://ollama.lab:{server.port}", pin=True, use_proxies=False, plain_http_hosts=("ollama.lab",)
    )
    server.script += [Reply(200, {}), Reply(200, {})]
    c.send("GET", "/")
    c.send("GET", "/")
    assert [h for h in resolved if h != "127.0.0.1"] == ["ollama.lab", "ollama.lab"], "resolved on every call"
    assert server.seen[0].headers["host"] == f"ollama.lab:{server.port}"


# --------------------------------------------------------------------------- proxies
def test_proxies_come_from_the_setting_and_loopback_never_uses_one():
    proxies = {"https": "http://user:p%40ss@127.0.0.1:3128", "no": "internal.example"}
    c = HttpClient("https://api.example.test", proxies=proxies)
    host, port, headers = c._proxy()
    assert (host, port) == ("127.0.0.1", 3128)
    assert headers["Proxy-Authorization"] == "Basic dXNlcjpwQHNz"
    assert HttpClient("https://internal.example", proxies=proxies)._proxy() is None
    assert HttpClient("http://127.0.0.1:9", proxies={"http": "http://127.0.0.1:3128"})._proxy() is None
    assert HttpClient("https://api.example.test", proxies=proxies, use_proxies=False)._proxy() is None
    assert HttpClient("https://api.example.test", proxies={})._proxy() is None
    assert HttpClient("https://api.example.test", proxies={"https": "127.0.0.1:3128"})._proxy()[:2] == (
        "127.0.0.1",
        3128,
    )
    with pytest.raises(NetworkError):
        HttpClient("https://api.example.test", proxies={"https": "https://127.0.0.1:3128"})._proxy()


def test_a_proxy_that_asks_to_sign_in_is_reported_as_such():
    proxy = FakeProxy("407 Proxy Authentication Required")
    try:
        c = HttpClient("https://api.example.test", proxies={"https": f"http://127.0.0.1:{proxy.port}"})
        with pytest.raises(NetworkError) as info:
            c.send("POST", "/v1/messages", headers={"x-api-key": "sk-test-secret-123456"}, body=b"{}")
        assert "sign in" in str(info.value) and "NTLM" in str(info.value)
        assert "sk-test-secret" not in str(info.value)
        assert proxy.requests[0].startswith("CONNECT api.example.test:443 HTTP/1.")
        assert "sk-test-secret" not in proxy.requests[0], "the key never reaches the proxy in clear"
    finally:
        proxy.close()


def test_a_failed_tls_handshake_through_a_proxy_is_a_network_error():
    proxy = FakeProxy("200 Connection established")
    try:
        c = HttpClient("https://api.example.test", proxies={"https": f"http://127.0.0.1:{proxy.port}"})
        with pytest.raises(NetworkError):
            c.send("GET", "/v1/models")
    finally:
        proxy.close()


# --------------------------------------------------------------------------- TLS
def test_tls_comes_from_truststore_when_it_is_installed(monkeypatch):
    import ssl

    made = []

    class FakeContext(ssl.SSLContext):
        def __new__(cls, protocol):
            made.append(protocol)
            return super().__new__(cls, protocol)

    monkeypatch.setitem(sys.modules, "truststore", types.SimpleNamespace(SSLContext=FakeContext))
    ctx = aihttp.default_ssl_context()
    assert isinstance(ctx, FakeContext) and made == [ssl.PROTOCOL_TLS_CLIENT]
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_tls_falls_back_to_the_standard_library(monkeypatch):
    import ssl

    monkeypatch.setitem(sys.modules, "truststore", None)  # import fails
    ctx = aihttp.default_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
