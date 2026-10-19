"""Each provider against a fake server on 127.0.0.1: the request it sends, where the key
goes, how it reads the reply and its usage, the output cap, the health check and its
cache, and the 401 path, where the key must appear nowhere. No real provider is called."""

import json
import logging
import socket
import threading
import time

import pytest

from ai_support import (
    KEY,
    FakeServer,
    Reply,
    Stall,
    anthropic_reply,
    gemini_reply,
    handle_of,
    mm,
    ollama_reply,
    openai_reply,
    plan_json,
    step,
    summary_of,
)
from solidseas.ai import CallOptions, Cancel, RunBudget, Secret
from solidseas.ai.base import Completion
from solidseas.ai.errors import (
    BudgetExceededError,
    CancelledError,
    InvalidSettingError,
    NetworkError,
    NoKeyError,
    PolicyRefusedError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitedError,
    ReplyInvalidError,
    UnauthorizedError,
)
from solidseas.ai.fake import ScriptedProvider
from solidseas.ai.providers import AnthropicProvider, GeminiProvider, OllamaProvider, OpenAIProvider
from solidseas.ai.usage import UsageLedger, estimate_tokens

S = summary_of()
EDGE = handle_of(S, "pr:edge:top0")
PLAN = plan_json(step("fillet", edges=[EDGE], radius=mm(1)))
DRAFT = json.dumps({"language": "python", "code": "print('hi')", "explanation": "Says hi."})

CASES = {
    "anthropic": (AnthropicProvider, anthropic_reply, "/v1/messages", "/v1/models/test-model"),
    "openai": (OpenAIProvider, openai_reply, "/v1/chat/completions", "/v1/models/test-model"),
    "gemini": (
        GeminiProvider,
        gemini_reply,
        "/v1beta/models/test-model:generateContent",
        "/v1beta/models/test-model",
    ),
    "ollama": (OllamaProvider, ollama_reply, "/api/chat", "/api/tags"),
}


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def ledger(tmp_path):
    return UsageLedger(str(tmp_path / "usage.json"))


def make(name, server, ledger=None, *, model_name="test-model", **kw):
    cls = CASES[name][0]
    if name != "ollama":
        kw.setdefault("key", Secret(KEY))
    kw.setdefault("http_options", {"backoff_base": 0.01})
    return cls(model=model_name, endpoint=server.url, ledger=ledger, **kw)


def _key_headers(name) -> dict:
    return {
        "anthropic": {"x-api-key": KEY},
        "openai": {"authorization": "Bearer " + KEY},
        "gemini": {"x-goog-api-key": KEY},
        "ollama": {},
    }[name]


# --------------------------------------------------------------------------- the request
@pytest.mark.parametrize("name", list(CASES))
def test_plan_steps_sends_the_shared_prompt_and_reads_the_reply(name, server, ledger):
    _, reply, path, _ = CASES[name]
    server.script.append(
        Reply(200, reply("```json\n" + PLAN + "\n```", input_tokens=1500, output_tokens=200))
    )
    provider = make(name, server, ledger)
    result = provider.plan_steps("Fillet the front top edge 1 mm", S)
    assert result.value.steps[0].op == "fillet" and result.value.steps[0].args["radius"].source == "you said"
    assert (result.input_tokens, result.output_tokens) == (1500, 200)
    seen = server.seen[0]
    assert seen.method == "POST" and seen.path == path
    body = seen.json()
    assert result.prompt.system in body_text(body) and result.prompt.user in body_text(body)
    assert S.text in body_text(body)
    for header, value in _key_headers(name).items():
        assert seen.headers[header] == value
    assert KEY not in seen.path and KEY not in seen.body.decode(), "the key travels only in a header"
    month = ledger.month()
    assert (month.calls, month.input_tokens, month.output_tokens) == (1, 1500, 200)


def body_text(body) -> str:
    """Every string in a request body, joined."""
    out = []

    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(body)
    return "\n".join(out)


def test_each_provider_shapes_its_request(server):
    server.script += [Reply(200, anthropic_reply(PLAN))]
    make("anthropic", server).plan_steps("fillet", S)
    b = server.seen[-1].json()
    assert (
        b["model"] == "test-model"
        and b["system"].startswith("You plan")
        and b["messages"][0]["role"] == "user"
    )
    assert server.seen[-1].headers["anthropic-version"] == "2023-06-01"
    assert b["max_tokens"] <= 8192

    server.script += [Reply(200, openai_reply(PLAN))]
    make("openai", server).plan_steps("fillet", S)
    b = server.seen[-1].json()
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert b["response_format"] == {"type": "json_object"} and b["max_completion_tokens"] <= 8192
    assert "temperature" not in b

    server.script += [Reply(200, gemini_reply(PLAN))]
    make("gemini", server).plan_steps("fillet", S)
    b = server.seen[-1].json()
    assert b["systemInstruction"]["parts"][0]["text"].startswith("You plan")
    assert b["generationConfig"]["responseMimeType"] == "application/json"
    assert b["generationConfig"]["maxOutputTokens"] <= 8192

    server.script += [Reply(200, ollama_reply(PLAN))]
    make("ollama", server).plan_steps("fillet", S)
    b = server.seen[-1].json()
    assert b["stream"] is False and b["format"] == "json" and b["options"]["num_predict"] <= 8192
    assert "authorization" not in server.seen[-1].headers


def _picture(width: int = 4, height: int = 3):
    from solidseas.ai.prompts import part_image
    from solidseas.formats._source import encode_png

    return part_image(
        encode_png(width, height, bytes(width * height * 3), 3), "The part from the front, right and above"
    )


def test_each_provider_sends_a_picture_after_the_text(server):
    import base64

    image = _picture()
    data = base64.b64encode(image.png).decode("ascii")
    server.script += [Reply(200, anthropic_reply(PLAN))]
    result = make("anthropic", server).plan_steps("fillet", S, image=image)
    text, picture = server.seen[-1].json()["messages"][0]["content"]
    assert (
        text == {"type": "text", "text": result.prompt.user}
        and "A picture of the part follows" in text["text"]
    )
    assert picture == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
    assert result.prompt.images == (image,) and image.line() in result.prompt.text()

    server.script += [Reply(200, openai_reply(DRAFT))]
    make("openai", server).draft_change(S, "fillet", image=image)
    text, picture = server.seen[-1].json()["messages"][1]["content"]
    assert text["type"] == "text" and picture == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + data},
    }

    server.script += [Reply(200, gemini_reply(PLAN))]
    make("gemini", server).plan_steps("fillet", S, image=image)
    parts = server.seen[-1].json()["contents"][0]["parts"]
    assert "text" in parts[0] and parts[1] == {"inline_data": {"mime_type": "image/png", "data": data}}

    server.script += [Reply(200, ollama_reply(PLAN))]
    make("ollama", server).plan_steps("fillet", S, image=image)
    user = server.seen[-1].json()["messages"][1]
    assert user["images"] == [data] and isinstance(user["content"], str)


@pytest.mark.parametrize("name", list(CASES))
def test_without_a_picture_the_request_is_as_before(name, server):
    _, reply, _, _ = CASES[name]
    server.script.append(Reply(200, reply(PLAN)))
    result = make(name, server).plan_steps("fillet", S)
    body = server.seen[-1].json()
    assert result.prompt.images == () and "[image]" not in result.prompt.text()
    assert "base64" not in json.dumps(body) and "images" not in json.dumps(body)
    assert "A picture of the part" not in result.prompt.user


def test_an_administrator_can_forbid_pictures(server, policy_reader):
    from solidseas.ai.base import IMAGES_MESSAGE
    from solidseas.policy import Policy

    policy_reader(lambda: Policy(images_disabled=True, locked=True))
    with pytest.raises(PolicyRefusedError) as caught:
        make("anthropic", server).plan_steps("fillet", S, image=_picture())
    assert str(caught.value) == IMAGES_MESSAGE and server.seen == []
    server.script.append(Reply(200, anthropic_reply(PLAN)))
    assert make("anthropic", server).plan_steps("fillet", S).value is not None  # text alone still goes


def test_a_picture_is_counted_before_the_call():
    from solidseas.ai.prompts import plan_prompt
    from solidseas.ai.usage import estimate_image_tokens, estimate_prompt_tokens

    plain, pictured = plan_prompt("fillet", S), plan_prompt("fillet", S, image=_picture(1000, 750))
    assert estimate_image_tokens(1000, 750) == 1100
    assert estimate_prompt_tokens(pictured) >= estimate_prompt_tokens(plain) + 1100


def test_only_a_png_within_the_limits_is_a_picture():
    from solidseas.ai.errors import InvalidSettingError
    from solidseas.ai.prompts import MAX_IMAGE_SIDE, part_image
    from solidseas.formats._source import encode_png

    good = _picture()
    assert (good.width, good.height) == (4, 3)
    for bad in (b"GIF89a" + bytes(40), good.png[:20], "not bytes"):
        with pytest.raises(InvalidSettingError):
            part_image(bad, "x")
    wide = MAX_IMAGE_SIDE + 1
    with pytest.raises(InvalidSettingError):
        part_image(encode_png(wide, 1, bytes(wide), 1), "x")
    assert part_image(good.png, "  two\n lines  ").caption == "two lines"


@pytest.mark.parametrize("name", list(CASES))
def test_draft_change_reads_a_draft(name, server):
    _, reply, _, _ = CASES[name]
    server.script.append(Reply(200, reply(DRAFT)))
    result = make(name, server).draft_change(S, "print hi")
    assert result.value.language == "python" and result.value.code == "print('hi')"
    assert result.prompt.task == "draft"


# --------------------------------------------------------------------------- the output cap
@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini", "ollama"])
def test_the_output_cap_sent_is_no_larger_than_the_run_budget_leaves(name, server, ledger):
    _, reply, _, _ = CASES[name]
    server.script.append(Reply(200, reply(PLAN)))
    run = RunBudget(10_000)
    result = make(name, server, ledger).plan_steps("fillet", S, call=CallOptions(run_budget=run))
    body = server.seen[0].json()
    cap = {
        "anthropic": lambda b: b["max_tokens"],
        "openai": lambda b: b["max_completion_tokens"],
        "gemini": lambda b: b["generationConfig"]["maxOutputTokens"],
        "ollama": lambda b: b["options"]["num_predict"],
    }
    estimate = estimate_tokens(result.prompt.system) + estimate_tokens(result.prompt.user)
    assert cap[name](body) == min(8192, 10_000 - estimate) < 8192
    assert run.used == 1200 + 300


def test_a_call_the_budget_cannot_cover_is_never_sent(server, ledger):
    with pytest.raises(BudgetExceededError):
        make("anthropic", server, ledger).plan_steps("fillet", S, call=CallOptions(run_budget=RunBudget(500)))
    assert server.seen == []


# --------------------------------------------------------------------------- replies
@pytest.mark.parametrize("name", list(CASES))
def test_a_truncated_reply_says_it_was_cut_off(name, server):
    _, reply, _, _ = CASES[name]
    flag = {
        "anthropic": {"stop": "max_tokens"},
        "openai": {"finish": "length"},
        "gemini": {"finish": "MAX_TOKENS"},
        "ollama": {"done": "length"},
    }[name]
    server.script.append(Reply(200, reply(PLAN[:40], **flag)))
    with pytest.raises(ReplyInvalidError) as info:
        make(name, server).plan_steps("fillet", S)
    assert "cut off" in str(info.value)


@pytest.mark.parametrize("name", list(CASES))
def test_a_reply_of_the_wrong_shape_is_a_provider_error(name, server):
    server.script.append(Reply(200, {"unexpected": True}))
    with pytest.raises(ProviderError):
        make(name, server).plan_steps("fillet", S)


@pytest.mark.parametrize("name", list(CASES))
def test_a_reply_that_is_not_a_valid_plan_is_refused(name, server, ledger):
    _, reply, _, _ = CASES[name]
    server.script.append(Reply(200, reply(plan_json(step("delete", features=["F1"])))))
    with pytest.raises(ReplyInvalidError):
        make(name, server, ledger).plan_steps("delete everything", S)
    assert ledger.month().calls == 1, "a refused reply still counts its tokens"


def test_gemini_blocked_and_thinking_replies(server):
    server.script.append(Reply(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ProviderError) as info:
        make("gemini", server).plan_steps("fillet", S)
    assert "SAFETY" in str(info.value)
    data = gemini_reply(PLAN, output_tokens=100)
    data["candidates"][0]["content"]["parts"].insert(0, {"text": "thinking...", "thought": True})
    data["usageMetadata"]["thoughtsTokenCount"] = 50
    server.script.append(Reply(200, data))
    result = make("gemini", server).plan_steps("fillet", S)
    assert result.output_tokens == 150 and result.raw == PLAN


def test_openai_refusal_is_a_refused_reply_whose_usage_counts(server, ledger):
    refusal = {"message": {"content": None, "refusal": "no"}, "finish_reason": "stop"}
    server.script.append(
        Reply(200, {"choices": [refusal], "usage": {"prompt_tokens": 900, "completion_tokens": 12}})
    )
    run = RunBudget(30_000)
    with pytest.raises(ReplyInvalidError) as info:
        make("openai", server, ledger).plan_steps("fillet", S, call=CallOptions(run_budget=run))
    assert "declined" in str(info.value)
    month = ledger.month()
    assert (month.calls, month.input_tokens, month.output_tokens) == (1, 900, 12)
    assert (run.used, run.held) == (912, 0)


# --------------------------------------------------------------------------- what a failed call costs
def _holds(ledger) -> dict:
    with open(ledger.path, encoding="utf-8") as fh:
        return json.load(fh)["holds"]


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


QUICK = {"backoff_base": 0.01, "connect_timeout": 0.5, "read_timeout": 0.5, "max_tries": 1}
DELIVERED = {
    "the server stalls (timeout)": (lambda s: s.script.append(Stall()), None, ProviderTimeoutError),
    "Stop while it works": (lambda s: s.script.append(Stall()), "stop", CancelledError),
    "a reply cut off": (
        lambda s: s.script.append(Reply(200, b'{"content": [{"type": "text", "text": "x"}], "usage": {')),
        None,
        ProviderError,
    ),
    "a reply of the wrong shape": (
        lambda s: s.script.append(Reply(200, {"content": 5})),
        None,
        ProviderError,
    ),
}


@pytest.mark.parametrize("case", list(DELIVERED))
def test_a_call_that_fails_after_the_provider_had_it_is_charged(case, server, ledger):
    """The provider received these requests, so it may bill for them; before the fix none
    was recorded and the run's budget was untouched, so failing calls cost tokens the
    budgets never saw. Each is charged its input estimate plus its output cap."""
    script, stop, error = DELIVERED[case]
    script(server)
    run = RunBudget(30_000)
    call = CallOptions(run_budget=run)
    if stop:
        call.cancel = Cancel()
        threading.Timer(0.3, call.cancel.cancel).start()
    provider = make("anthropic", server, ledger, http_options=QUICK)
    with pytest.raises(error) as info:
        provider.draft_change(None, "make a box", call=call)
    assert info.value.delivered and len(server.seen) == 1
    sent = server.seen[0].json()
    prompt_tokens = estimate_tokens(sent["system"]) + estimate_tokens(sent["messages"][0]["content"])
    charge = prompt_tokens + sent["max_tokens"]
    month = ledger.month()
    assert (month.calls, month.tokens) == (1, charge)
    assert (run.used, run.held) == (charge, 0)
    assert _holds(ledger) == {}


NOT_DELIVERED = {
    "401": (Reply(401, {"error": {"message": "bad key"}}), UnauthorizedError),
    "400": (Reply(400, {"error": {"message": "bad request"}}), ProviderError),
    "429": (Reply(429, {"error": {"message": "slow down"}}), RateLimitedError),
}


@pytest.mark.parametrize("case", [*NOT_DELIVERED, "nothing listening"])
def test_a_call_the_provider_refused_or_never_got_costs_nothing(case, server, ledger):
    run = RunBudget(30_000)
    if case == "nothing listening":
        provider = AnthropicProvider(
            model="test-model",
            key=Secret(KEY),
            endpoint=f"http://127.0.0.1:{_closed_port()}",
            ledger=ledger,
            http_options=QUICK,
        )
        error = (NetworkError, ProviderTimeoutError)
    else:
        reply, error = NOT_DELIVERED[case]
        server.script.append(reply)
        provider = make("anthropic", server, ledger, http_options=QUICK)
    with pytest.raises(error) as info:
        provider.draft_change(None, "make a box", call=CallOptions(run_budget=run))
    assert not info.value.delivered
    assert ledger.month().calls == 0 and (run.used, run.held) == (0, 0)
    assert _holds(ledger) == {}, "the hold was given back"


def test_stop_pressed_as_the_reply_arrives_discards_it_and_counts_it(tmp_path):
    """The call returned the draft although Stop had been pressed while it was read."""
    ledger = UsageLedger(str(tmp_path / "usage.json"))
    stop = Cancel()

    def reply(prompt):
        stop.cancel()  # pressed while the reply was on its way
        return Completion(DRAFT, input_tokens=100, output_tokens=20)

    provider = ScriptedProvider([reply], ledger=ledger)
    with pytest.raises(CancelledError):
        provider.draft_change(None, "make a cube", call=CallOptions(cancel=stop))
    assert ledger.month().tokens == 120


def test_missing_usage_is_estimated(server, ledger):
    server.script.append(Reply(200, {"content": [{"type": "text", "text": PLAN}], "stop_reason": "end_turn"}))
    result = make("anthropic", server, ledger).plan_steps("fillet", S)
    assert result.input_tokens > 1000 and result.output_tokens > 10


# --------------------------------------------------------------------------- the key
@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini"])
def test_a_401_with_a_known_key_shows_the_key_nowhere(name, server, ledger, caplog):
    caplog.set_level(logging.DEBUG)
    body = {"error": {"message": f"Incorrect API key provided: {KEY[:8]}...{KEY[-4:]} ({KEY})"}}
    server.script.append(Reply(401, body))
    provider = make(name, server, ledger)
    with pytest.raises(UnauthorizedError) as info:
        provider.plan_steps("fillet", S)
    shown = [
        str(info.value),
        repr(info.value),
        str(info.value.detail),
        repr(provider),
        str(provider.__dict__),
        caplog.text,
        provider.health().message,
    ]
    for text in shown:
        assert KEY not in text and KEY[-12:] not in text and KEY[8:20] not in text
    assert len(server.seen) == 2, "the call and the health check, each once: a 401 is never retried"
    assert "settings" in str(info.value)


def test_a_provider_needs_its_key_passed_explicitly(server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    with pytest.raises(NoKeyError):
        AnthropicProvider(model="test-model", endpoint=server.url)
    with pytest.raises(NoKeyError):
        OpenAIProvider(model="test-model", key=KEY, endpoint=server.url)  # text, not a Secret


SHAPED_KEYS = {
    # no two digits side by side: the fake server's port in an error is never a piece of the key
    "gemini": "AIzaSy" + "Q7wErTyUiOpAsDfGhJkLzXcVbNm1a2b3c",
    "anthropic": "sk-ant-api03-" + "Zq9Xw" * 19,
    "openai": "sk-proj-" + "Ab3dE" * 30,
}
PUBLIC_PREFIX = {"gemini": "AIzaSy", "anthropic": "sk-ant-api03-", "openai": "sk-proj-"}


def _longest_piece(secret: str, text: str) -> int:
    """The length of the longest run of ``secret`` that appears in ``text``."""
    best = 0
    for i in range(len(secret)):
        while i + best < len(secret) and secret[i : i + best + 1] in text:
            best += 1
    return best


@pytest.mark.parametrize("name", list(SHAPED_KEYS))
def test_a_key_the_200_character_cut_splits_is_still_hidden(name, server):
    """The message was cut to 200 characters before the scrub, so a key the cut split no
    longer matched; up to 7 secret characters of a Gemini key reached the error."""
    key = SHAPED_KEYS[name]
    secret = key[len(PUBLIC_PREFIX[name]) :]
    worst = 0
    for lead in range(150, 201):
        server.script.append(Reply(400, {"error": {"message": "x" * lead + " header was " + key}}))
        provider = make(name, server, key=Secret(key), http_options={"max_tries": 1})
        with pytest.raises(ProviderError) as info:
            provider.draft_change(None, "make a box")
        worst = max(worst, _longest_piece(secret, str(info.value)))
    assert worst < 4, f"{worst} characters of the key reached the message"


def test_provider_text_quoted_in_an_error_is_scrubbed(server):
    server.script.append(
        Reply(400, {"error": {"message": f"bad request for key {KEY} and sk-other-abcdef1234"}})
    )
    with pytest.raises(ProviderError) as info:
        make("anthropic", server).plan_steps("fillet", S)
    assert (
        KEY not in str(info.value) and "sk-other" not in str(info.value) and "status 400" in str(info.value)
    )


# --------------------------------------------------------------------------- health
@pytest.mark.parametrize("name", list(CASES))
def test_health_is_checked_at_most_hourly(name, server):
    _, _, _, health_path = CASES[name]
    server.default = Reply(200, {"models": [{"name": "test-model:latest"}]})
    provider = make(name, server)
    first = provider.health()
    assert first.ok, first.message
    assert provider.health().checked_at == first.checked_at
    assert len(server.seen) == 1 and server.seen[0].method == "GET" and server.seen[0].path == health_path
    provider.health(now=time.time() + 3601)
    provider.health(refresh=True)
    assert len(server.seen) == 3


def test_ollama_health_says_when_the_model_is_missing(server):
    server.default = Reply(200, {"models": [{"name": "other:7b"}]})
    result = make("ollama", server).health()
    assert not result.ok and "Pull it" in result.message


@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini"])
def test_cloud_health_says_when_the_model_is_missing(name, server):
    """Anthropic and OpenAI asked only for the list of models, so any answer passed and a
    misspelled model failed only on the first real call."""
    server.default = Reply(404, {"error": {"message": "model: no-such-model"}})
    result = make(name, server).health()
    assert not result.ok and "test-model" in result.message and "settings" in result.message
    assert server.seen[0].path == CASES[name][3]


def test_a_model_name_stays_one_path_segment_in_the_health_check(server):
    server.default = Reply(200, {"id": "x"})
    assert make("anthropic", server, model_name="a/b").health().ok
    assert make("openai", server, model_name="ft:gpt-x:org::abc").health().ok
    assert [s.path for s in server.seen] == ["/v1/models/a%2Fb", "/v1/models/ft:gpt-x:org::abc"]


def test_health_never_raises(server):
    server.default = Reply(500, b"boom")
    assert not make("openai", server).health().ok


# --------------------------------------------------------------------------- the guard and Stop
def test_the_guard_runs_before_every_call_and_health_check(server):
    allowed = [True]

    def guard():
        if not allowed[0]:
            raise PolicyRefusedError("Set by your administrator.")

    server.default = Reply(200, anthropic_reply(PLAN))
    provider = make("anthropic", server, guard=guard)
    provider.plan_steps("fillet", S)
    allowed[0] = False
    with pytest.raises(PolicyRefusedError):
        provider.plan_steps("fillet", S)
    assert not provider.health(refresh=True).ok
    assert len(server.seen) == 1, "nothing was sent once the policy refused"


def test_stop_before_the_call_sends_nothing(server):
    cancel = Cancel()
    cancel.cancel()
    with pytest.raises(CancelledError):
        make("openai", server).plan_steps("fillet", S, call=CallOptions(cancel=cancel))
    assert server.seen == []


# --------------------------------------------------------------------------- model names
@pytest.mark.parametrize("model", ["", "a b", "x" * 200, "../etc", "model?key=1", None])
def test_model_names_are_checked(model, server):
    with pytest.raises(InvalidSettingError):
        AnthropicProvider(model=model, key=Secret(KEY), endpoint=server.url)


def test_gemini_model_names_cannot_change_the_path(server):
    assert GeminiProvider(model="models/gemini-x", key=Secret(KEY), endpoint=server.url).model == "gemini-x"
    for bad in ("a/b", "a:generateContent", "x?y"):
        with pytest.raises(InvalidSettingError):
            GeminiProvider(model=bad, key=Secret(KEY), endpoint=server.url)


def test_cloud_providers_default_to_https_endpoints():
    assert AnthropicProvider(model="m", key=Secret(KEY)).endpoint == "https://api.anthropic.com"
    assert OpenAIProvider(model="m", key=Secret(KEY)).endpoint == "https://api.openai.com"
    assert GeminiProvider(model="m", key=Secret(KEY)).endpoint == "https://generativelanguage.googleapis.com"
    assert OllamaProvider(model="m").endpoint == "http://127.0.0.1:11434"
    with pytest.raises(InvalidSettingError):
        AnthropicProvider(model="m", key=Secret(KEY), endpoint="http://api.example.test")


def test_stop_ends_a_call_in_flight_and_a_passed_deadline_sends_nothing():
    import threading

    from solidseas.ai.errors import ProviderTimeoutError
    from solidseas.ai.fake import WAIT_FOR_CANCEL, ScriptedProvider

    provider = ScriptedProvider([WAIT_FOR_CANCEL])
    stop = Cancel()
    threading.Timer(0.2, stop.cancel).start()
    start = time.monotonic()
    with pytest.raises(CancelledError):
        provider.draft_change(None, "make a cube", call=CallOptions(cancel=stop))
    assert time.monotonic() - start < 5
    provider = ScriptedProvider([DRAFT])
    with pytest.raises(ProviderTimeoutError):
        provider.draft_change(None, "make a cube", call=CallOptions(deadline=time.monotonic() - 1))
    assert provider.prompts == []
