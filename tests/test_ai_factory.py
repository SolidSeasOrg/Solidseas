"""The factory: the only place a provider is built, one of the two policy chokepoints, the
cache and its reset, the reasons it serves noop with, and the AI settings it reads."""

import ast
import math
import re
from pathlib import Path

import pytest

from ai_support import KEY, FakeServer, Reply, anthropic_reply, handle_of, mm, plan_json, step, summary_of
from solidseas.ai import AISettings, MemoryCredentialStore, Secret, factory
from solidseas.ai.errors import CredentialStoreError, InvalidSettingError, PolicyRefusedError
from solidseas.ai.providers import (
    AnthropicProvider,
    GeminiProvider,
    NoopProvider,
    OllamaProvider,
    OpenAIProvider,
)
from solidseas.ai.usage import UsageLedger
from solidseas.policy import NO_POLICY, Policy

SRC = Path(__file__).parents[1] / "src"


@pytest.fixture(autouse=True)
def fresh_factory():
    factory.reset()
    yield
    factory.reset()


@pytest.fixture
def store():
    return MemoryCredentialStore({"anthropic": KEY, "openai": KEY, "gemini": KEY})


@pytest.fixture
def ledger(tmp_path):
    return UsageLedger(str(tmp_path / "usage.json"))


def test_nothing_configured_is_noop_and_hidden():
    p = factory.get_provider(AISettings())
    assert isinstance(p, NoopProvider) and p.reason == "not_configured" and not p.set_by_administrator
    assert p.plan_steps("x", None) is None and p.draft_change(None, "x") is None, (
        "a capability gap, not an error"
    )
    assert not p.health().ok


@pytest.mark.parametrize(
    "provider, cls",
    [("anthropic", AnthropicProvider), ("openai", OpenAIProvider), ("gemini", GeminiProvider)],
)
def test_cloud_providers_get_their_key_from_the_store(provider, cls, store, ledger):
    p = factory.get_provider(
        AISettings(provider=provider, model="test-model"), credentials=store, ledger=ledger
    )
    assert type(p) is cls and p.model == "test-model" and p.ledger is ledger
    assert KEY not in repr(p)


def test_ollama_needs_no_key(ledger):
    p = factory.get_provider(AISettings(provider="ollama", model="llama3"), ledger=ledger)
    assert type(p) is OllamaProvider and p.endpoint == "http://127.0.0.1:11434" and p.local


def test_missing_pieces_give_noop_with_the_reason(ledger):
    empty = MemoryCredentialStore()
    p = factory.get_provider(AISettings(provider="anthropic", model="m"), credentials=empty, ledger=ledger)
    assert isinstance(p, NoopProvider) and p.reason == "no_key" and "Anthropic" in p.message
    p = factory.get_provider(AISettings(provider="anthropic"), credentials=empty, ledger=ledger)
    assert p.reason == "not_configured" and "model" in p.message

    class Broken(MemoryCredentialStore):
        def get(self, provider):
            raise CredentialStoreError(
                "Windows Credential Manager could not read SolidSeas/anthropic (error 5)."
            )

    p = factory.get_provider(AISettings(provider="anthropic", model="m"), credentials=Broken(), ledger=ledger)
    assert p.reason == "credential_store" and "error 5" in p.message
    p = factory.get_provider(AISettings(provider="ollama", model="m", ollama_url="ftp://x"), ledger=ledger)
    assert p.reason == "invalid_setting"


def test_the_default_store_is_used_when_none_is_given():
    p = factory.get_provider(AISettings(provider="openai", model="m"))
    assert isinstance(p, NoopProvider) and p.reason == "no_key"  # the tests' default store is empty


def test_the_provider_is_cached_until_reset(store, ledger):
    s = AISettings(provider="anthropic", model="m")
    a = factory.get_provider(s, credentials=store, ledger=ledger)
    assert factory.get_provider(s, credentials=store, ledger=ledger) is a
    assert (
        factory.get_provider(AISettings(provider="anthropic", model="m2"), credentials=store, ledger=ledger)
        is not a
    )
    b = factory.get_provider(s, credentials=store, ledger=ledger)
    factory.reset()
    assert factory.get_provider(s, credentials=store, ledger=ledger) is not b


def test_a_policy_pushed_while_the_app_runs_applies_to_the_next_call(store, ledger, policy_reader):
    server = FakeServer()
    try:
        summary = summary_of()
        reply = anthropic_reply(
            plan_json(step("fillet", edges=[handle_of(summary, "pr:edge:top0")], radius=mm(1)))
        )
        server.default = Reply(200, reply)
        settings = AISettings(provider="anthropic", model="m")
        p = factory.get_provider(settings, credentials=store, ledger=ledger)
        p._http = type(p._http)(server.url, scrub=p._scrub)  # point the cached provider at the fake server
        p.plan_steps("fillet 1 mm", summary)
        assert len(server.seen) == 1
        policy_reader(Policy(local_only=True, locked=True))
        with pytest.raises(PolicyRefusedError) as info:
            p.plan_steps("fillet 1 mm", summary)
        assert "administrator" in str(info.value)
        assert len(server.seen) == 1, "nothing was sent"
        refused = factory.get_provider(settings, credentials=store, ledger=ledger)
        assert isinstance(refused, NoopProvider) and refused.reason == "policy_refused"
        policy_reader(NO_POLICY)
        assert factory.get_provider(settings, credentials=store, ledger=ledger) is p
    finally:
        server.close()


def test_health_reads_the_policy_before_its_cache(store, ledger, policy_reader):
    """health() returned its cached ok for up to an hour after LocalProviderOnly was set."""
    server = FakeServer()
    try:
        server.default = Reply(200, {"id": "m"})
        p = factory.get_provider(
            AISettings(provider="anthropic", model="m"), credentials=store, ledger=ledger
        )
        p._http = type(p._http)(server.url, scrub=p._scrub)
        assert p.health().ok and len(server.seen) == 1
        policy_reader(Policy(local_only=True, locked=True))
        refused = p.health()
        assert not refused.ok and "administrator" in refused.message
        assert len(server.seen) == 1, "nothing was sent"
        policy_reader(NO_POLICY)
        assert p.health().ok and len(server.seen) == 2, "the cache was dropped, so it checks again"
    finally:
        server.close()


@pytest.mark.parametrize(
    "url, hosts, allowed",
    [
        ("http://127.0.0.1:11434", (), True),
        ("http://localhost:11434", (), True),
        ("http://[::1]:11434", (), True),
        ("http://127.0.0.5:11434", (), True),
        ("http://LocalHost.:11434", (), True),
        ("http://ollama.lab:11434", ("ollama.lab",), True),
        ("https://ollama.lab", ("ollama.lab",), True),
        ("http://ollama.lab.evil.example:11434", ("ollama.lab",), False),
        ("http://192.0.2.5:11434", ("ollama.lab",), False),
        ("http://192.0.2.5:11434", ("192.0.2.5",), True),
        ("http://0.0.0.0:11434", (), False),
        ("http://[::ffff:127.0.0.1]:11434", (), True),
        ("http://[::ffff:192.0.2.5]:11434", (), False),
    ],
)
def test_local_only_allows_loopback_and_listed_hosts_only(url, hosts, allowed, policy_reader, ledger):
    policy_reader(Policy(local_only=True, allowed_hosts=hosts, locked=True))
    settings = AISettings(provider="ollama", model="llama3", ollama_url=url)
    assert (factory.refusal(settings, Policy(local_only=True, allowed_hosts=hosts)) is None) is allowed
    p = factory.get_provider(settings, ledger=ledger)
    assert isinstance(p, NoopProvider) is (not allowed)


def test_local_only_refuses_every_cloud_provider(policy_reader, store, ledger):
    policy_reader(Policy(local_only=True, allowed_hosts=("api.anthropic.com",), locked=True))
    for name in ("anthropic", "openai", "gemini"):
        p = factory.get_provider(AISettings(provider=name, model="m"), credentials=store, ledger=ledger)
        assert isinstance(p, NoopProvider) and p.reason == "policy_refused", name


PROVIDER_NAMES = frozenset(
    {
        "AnthropicProvider",
        "OpenAIProvider",
        "GeminiProvider",
        "OllamaProvider",
        "NoopProvider",
        "CLOUD_PROVIDERS",
        "LOCAL_PROVIDERS",
    }
)


def provider_references(source: str) -> list[int]:
    """Lines of ``source`` that name a provider class or a provider table, in any form
    (a call, a subscript, an attribute, an alias), or import the providers package or
    anything from it other than the shared base class."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in PROVIDER_NAMES:
            lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in PROVIDER_NAMES:
            lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any("providers" in a.name.split(".") for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            from_providers = "providers" in (node.module or "").split(".")
            names = {a.name for a in node.names}
            if (
                "providers" in names
                or names & PROVIDER_NAMES
                or (from_providers and names != {"ChatProvider"})
            ):
                lines.append(node.lineno)
    return sorted(set(lines))


@pytest.mark.parametrize(
    "line",
    [
        'p = CLOUD_PROVIDERS["anthropic"](model="m", key=key)',
        'p = providers.LOCAL_PROVIDERS["ollama"](model="m", endpoint=url)',
        "from solidseas.ai.providers import AnthropicProvider as Claude",
        "from solidseas.ai.providers.anthropic import Something",
        "from solidseas.ai import providers",
        "import solidseas.ai.providers.openai as o",
        "from .providers import *",
        "p = mod.OpenAIProvider(model='m')",
    ],
)
def test_the_search_catches_every_way_of_reaching_a_provider(line):
    """The search was a regex for ``AnthropicProvider(`` and the like, which missed the
    provider tables (how the factory itself builds cloud providers) and an aliased import."""
    assert provider_references(line) == [1]


def test_providers_are_constructed_only_in_the_factory():
    """The search the security review records: outside solidseas/ai/factory.py and the
    providers' own package, nothing in src names a provider class or table or imports the
    package (fake.py, the test stand-in, takes only the shared base class)."""
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "solidseas/ai/factory.py" or rel.startswith("solidseas/ai/providers/"):
            continue
        hits += [f"{rel}:{n}" for n in provider_references(path.read_text(encoding="utf-8"))]
    assert hits == []
    assert provider_references((SRC / "solidseas/ai/factory.py").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini"])
def test_a_provider_built_outside_the_factory_still_obeys_the_policy(name, policy_reader):
    """Built without the factory, a provider had no guard and ignored LocalProviderOnly: a
    cloud provider built from the table sent its request. It now checks the policy itself,
    from its own kind and address."""
    from solidseas.ai.providers import CLOUD_PROVIDERS

    server = FakeServer()
    try:
        server.default = Reply(200, anthropic_reply("{}"))
        provider = CLOUD_PROVIDERS[name](model="m", key=Secret(KEY), endpoint=server.url)
        policy_reader(Policy(local_only=True, locked=True))
        with pytest.raises(PolicyRefusedError):
            provider.draft_change(None, "make a box")
        assert not provider.health(refresh=True).ok
        assert server.seen == [], "nothing was sent"
    finally:
        server.close()


def test_an_ollama_built_outside_the_factory_checks_its_own_address(policy_reader):
    near = OllamaProvider(model="llama3")
    far = OllamaProvider(model="llama3", endpoint="http://192.0.2.5:11434")
    lab = Policy(local_only=True, allowed_hosts=("192.0.2.5",), locked=True)
    assert near._allowed_by(Policy(local_only=True)) and far._allowed_by(lab)
    assert not far._allowed_by(Policy(local_only=True, allowed_hosts=("ollama.lab",)))
    policy_reader(Policy(local_only=True, locked=True))
    with pytest.raises(PolicyRefusedError):
        far.draft_change(None, "make a box")  # refused before any connection is tried
    from solidseas.ai.fake import ScriptedProvider

    draft = '{"language": "python", "code": "x = 1", "explanation": ""}'
    assert ScriptedProvider([draft]).draft_change(None, "make a box").value.code == "x = 1"
    with pytest.raises(PolicyRefusedError):
        ScriptedProvider([draft], local=False).draft_change(None, "make a box")


def test_start_run_is_the_only_entry_to_automatic_mode():
    # The assistant's window and the MCP server start runs, only through start_run, whose
    # checks make the RunStart an AutomaticRun needs; nothing else makes one.
    callers, makers = [], []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bstart_run\(", text) and rel != "solidseas_app/assistant/automatic.py":
            callers.append(rel)
        if re.search(r"\bRunStart\(", text) and rel != "solidseas_app/assistant/automatic.py":
            makers.append(rel)
    assert callers == ["solidseas_app/assistant/mcp_server.py", "solidseas_app/assistant/window.py"]
    assert makers == []


# --------------------------------------------------------------------------- settings
def test_settings_round_trip_and_defaults():
    s = AISettings.from_dict(
        {
            "provider": "openai",
            "model": "m",
            "monthly_cost": 20,
            "price_input_per_mtok": 2.5,
            "price_output_per_mtok": 10,
            "protected_properties": ["ERP Code"],
            "unknown": 1,
        }
    )
    assert s.provider == "openai" and s.protected_properties == ("ERP Code",)
    assert AISettings.from_dict(s.to_dict()) == s
    assert s.budget().pricing.output_per_mtok == 10 and s.limits().protected_properties == ("ERP Code",)
    d = AISettings()
    assert (d.monthly_tokens, d.run_tokens, d.max_steps, d.max_new_instances, d.always_confirm) == (
        2_000_000,
        30_000,
        20,
        200,
        False,
    )


@pytest.mark.parametrize(
    "data",
    [
        {"provider": "azure"},
        {"provider": "openai", "model": "bad model"},
        {"monthly_tokens": -5},
        {"monthly_cost": math.nan},
        {"price_input_per_mtok": 1.0},  # without the output price
        {"max_steps": 99},
        {"min_length_mm": 0.0001},
        {"run_tokens": "lots"},
        {"always_confirm": "yes"},
        {"protected_properties": ["x" * 65]},
        {"ollama_url": 5},
        [],
    ],
)
def test_bad_settings_are_refused(data):
    with pytest.raises(InvalidSettingError):
        AISettings.from_dict(data)
