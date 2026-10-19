"""The machine policy is read fail-closed, and both chokepoints honour every result.

Every branch of ``docs/ASSISTANT.md`` ("Machine policy") has a test: key absent, key
access denied, value absent, wrong type, out-of-range value, a read that raises, and
``AllowedProviderHosts`` of the wrong type; and the provider factory and ``start_run``
each honour each result. The real registry is only read, at a key that does not exist.
"""

import sys
import uuid

import pytest

from ai_support import REG_DWORD, REG_MULTI_SZ, REG_SZ, FakeRegistry, FakeTarget, said_plan
from solidseas import policy
from solidseas.ai import AISettings, MemoryCredentialStore, factory
from solidseas.ai.providers import NoopProvider
from solidseas.policy import NO_POLICY, Policy, read_policy

WINDOWS = sys.platform == "win32"


def _read(values=None, **kw) -> Policy:
    return read_policy(FakeRegistry(values, **kw))


# --------------------------------------------------------------------------- the key
def test_an_absent_key_means_no_policy():
    p = _read(None)
    assert p == NO_POLICY
    assert not p.automatic_disabled and not p.local_only and p.allowed_hosts == () and not p.locked
    assert p.error is None


def test_a_key_that_access_is_denied_to_turns_every_restriction_on():
    p = _read(open_error=PermissionError(13, "Access is denied"))
    assert p.automatic_disabled and p.local_only and p.allowed_hosts == () and p.locked
    assert "could not be read" in p.error and "every restriction is on" in p.error


def test_any_other_error_opening_the_key_turns_every_restriction_on():
    p = _read(open_error=OSError(1018, "illegal operation on a key marked for deletion"))
    assert p.automatic_disabled and p.local_only and p.locked and p.error


def test_a_present_key_with_no_values_restricts_nothing_but_is_locked():
    reg = FakeRegistry({})
    p = read_policy(reg)
    assert not p.automatic_disabled and not p.local_only and p.allowed_hosts == ()
    assert p.locked and p.error is None
    assert reg.closed == 1


@pytest.mark.parametrize("value, expected", [(0, False), (1, True)])
def test_dword_values_0_and_1(value, expected):
    p = _read({policy.DISABLE_AUTOMATIC: (value, REG_DWORD), policy.LOCAL_ONLY: (value, REG_DWORD)})
    assert p.automatic_disabled is expected and p.local_only is expected and p.error is None


@pytest.mark.parametrize(
    "raw",
    [
        ("1", REG_SZ),  # wrong registry type
        (b"\x01\x00\x00\x00", 3),  # REG_BINARY
        (["1"], REG_MULTI_SZ),
        (2, REG_DWORD),  # out of range
        (0xFFFFFFFF, REG_DWORD),
        (True, REG_DWORD),  # not an int
        (None, REG_DWORD),
    ],
)
def test_a_wrong_type_or_out_of_range_value_turns_that_restriction_on(raw):
    p = _read({policy.DISABLE_AUTOMATIC: raw})
    assert p.automatic_disabled and not p.local_only, "only the bad value's restriction is on"
    assert policy.DISABLE_AUTOMATIC in p.error
    p = _read({policy.LOCAL_ONLY: raw})
    assert p.local_only and not p.automatic_disabled


@pytest.mark.parametrize(
    "raw, expected", [((0, REG_DWORD), False), ((1, REG_DWORD), True), (("1", REG_SZ), True)]
)
def test_disable_images_is_read_as_the_other_flags(raw, expected):
    p = _read({policy.DISABLE_IMAGES: raw})
    assert p.images_disabled is expected and not p.automatic_disabled and not p.local_only
    assert _read({}).images_disabled is False
    assert _read(open_error=PermissionError(13, "denied")).images_disabled, (
        "an unreadable key forbids pictures too"
    )


def test_extensions_can_be_switched_off_or_limited_to_a_list():
    assert _read({}).allowed_extensions is None and policy.extension_allowed(_read({}), "video")
    off = _read({policy.DISABLE_EXTENSIONS: (1, REG_DWORD)})
    assert off.extensions_disabled and not policy.extension_allowed(off, "gridfinity")
    some = _read(
        {policy.ALLOWED_EXTENSIONS: ([" Gridfinity ", "video", "not an id!", "video"], REG_MULTI_SZ)}
    )
    assert some.allowed_extensions == ("gridfinity", "video") and "not an extension id" in some.error
    assert policy.extension_allowed(some, "video") and not policy.extension_allowed(some, "occt")
    wrong = _read({policy.ALLOWED_EXTENSIONS: ("gridfinity", REG_SZ)})
    assert wrong.allowed_extensions == () and not policy.extension_allowed(wrong, "gridfinity")
    unreadable = _read(open_error=PermissionError(13, "denied"))
    assert unreadable.extensions_disabled and unreadable.allowed_extensions == ()


def test_a_value_that_cannot_be_read_turns_that_restriction_on():
    p = _read({policy.LOCAL_ONLY: PermissionError(13, "denied"), policy.DISABLE_AUTOMATIC: (0, REG_DWORD)})
    assert p.local_only and not p.automatic_disabled and "could not be read" in p.error


def test_allowed_hosts_are_normalised_and_bad_entries_dropped():
    hosts = [
        "Ollama.Lab.Internal.",
        "  198.51.100.3 ",
        "[::1]",
        "",
        "not a host!",
        "ollama.lab.internal",
        "a_b.example",
    ]
    p = _read({policy.LOCAL_ONLY: (1, REG_DWORD), policy.ALLOWED_HOSTS: (hosts, REG_MULTI_SZ)})
    assert p.local_only
    assert p.allowed_hosts == ("ollama.lab.internal", "198.51.100.3", "::1")
    assert "not host names" in p.error


@pytest.mark.parametrize("raw", [("ollama.lab.internal", REG_SZ), (1, REG_DWORD), ("x", REG_MULTI_SZ)])
def test_allowed_hosts_of_the_wrong_type_count_as_empty(raw):
    p = _read({policy.LOCAL_ONLY: (1, REG_DWORD), policy.ALLOWED_HOSTS: raw})
    assert p.local_only and p.allowed_hosts == ()
    assert policy.ALLOWED_HOSTS in p.error


def test_allowed_hosts_are_capped():
    hosts = [f"h{i}.example" for i in range(policy.MAX_ALLOWED_HOSTS + 5)]
    p = _read({policy.ALLOWED_HOSTS: (hosts, REG_MULTI_SZ)})
    assert len(p.allowed_hosts) == policy.MAX_ALLOWED_HOSTS


def test_a_registry_that_fails_in_another_way_restricts_everything():
    class Broken(FakeRegistry):
        def query(self, key, name):
            raise RuntimeError("unexpected")

    p = read_policy(Broken({}))
    assert p.automatic_disabled and p.local_only and p.error


# --------------------------------------------------------------------------- current() and the reader
def test_a_reader_that_raises_means_every_restriction_is_on(policy_reader):
    def boom():
        raise OSError("registry service stopped")

    policy_reader(boom)
    p = policy.current()
    assert p.automatic_disabled and p.local_only and p.locked and "OSError" in p.error


def test_a_reader_that_returns_something_else_means_every_restriction_is_on(policy_reader):
    policy_reader(lambda: {"automatic_disabled": False})
    p = policy.current()
    assert p.automatic_disabled and p.local_only


def test_current_reads_fresh_on_every_call(policy_reader):
    calls = []

    def reader():
        calls.append(1)
        return Policy(local_only=len(calls) > 1)

    policy_reader(reader)
    assert not policy.current().local_only
    assert policy.current().local_only
    assert len(calls) == 2


def test_set_reader_returns_the_previous_and_none_restores_the_registry_reader():
    previous = policy.set_reader(None)
    try:
        assert policy.set_reader(previous) is policy.read_policy
    finally:
        policy.set_reader(previous)


def test_without_a_registry_there_is_no_policy(monkeypatch):
    monkeypatch.setattr(policy.sys, "platform", "linux")
    assert read_policy() == NO_POLICY


@pytest.mark.skipif(not WINDOWS, reason="the registry is Windows only")
def test_the_real_reader_opens_the_64_bit_view_and_treats_a_missing_key_as_no_policy(monkeypatch):
    monkeypatch.setattr(policy, "KEY_PATH", rf"SOFTWARE\Policies\SolidSeas-test-absent-{uuid.uuid4().hex}")
    assert read_policy() == NO_POLICY


def test_the_reader_never_checks_existence_first():
    import inspect

    code = inspect.getsource(policy)
    for banned in ("os.path.exists", "QueryInfoKey", "EnumValue", "EnumKey"):
        assert banned not in code


# --------------------------------------------------------------------------- both chokepoints honour it
BRANCHES = {
    "key absent": (None, {}),
    "key access denied": (None, {"open_error": PermissionError(13, "denied")}),
    "values absent": ({}, {}),
    "automatic off": ({policy.DISABLE_AUTOMATIC: (1, REG_DWORD)}, {}),
    "local only": ({policy.LOCAL_ONLY: (1, REG_DWORD)}, {}),
    "wrong type": ({policy.LOCAL_ONLY: ("1", REG_SZ), policy.DISABLE_AUTOMATIC: ("0", REG_SZ)}, {}),
    "out of range": ({policy.LOCAL_ONLY: (7, REG_DWORD), policy.DISABLE_AUTOMATIC: (7, REG_DWORD)}, {}),
    "value unreadable": ({policy.LOCAL_ONLY: PermissionError(13, "denied")}, {}),
    "hosts wrong type": ({policy.LOCAL_ONLY: (1, REG_DWORD), policy.ALLOWED_HOSTS: ("lab", REG_SZ)}, {}),
    "hosts listed": (
        {policy.LOCAL_ONLY: (1, REG_DWORD), policy.ALLOWED_HOSTS: (["lab.internal"], REG_MULTI_SZ)},
        {},
    ),
}
# branch: (cloud allowed, loopback Ollama allowed, Ollama at lab.internal allowed, Automatic allowed)
EXPECTED = {
    "key absent": (True, True, True, True),
    "key access denied": (False, True, False, False),
    "values absent": (True, True, True, True),
    "automatic off": (True, True, True, False),
    "local only": (False, True, False, True),
    "wrong type": (False, True, False, False),
    "out of range": (False, True, False, False),
    "value unreadable": (False, True, False, True),
    "hosts wrong type": (False, True, False, True),
    "hosts listed": (False, True, True, True),
}


@pytest.mark.parametrize("branch", list(BRANCHES))
def test_the_factory_honours_each_result(branch, policy_reader, tmp_path):
    values, kw = BRANCHES[branch]
    policy_reader(lambda: read_policy(FakeRegistry(values, **kw)))
    cloud_ok, loopback_ok, lab_ok, _ = EXPECTED[branch]
    store = MemoryCredentialStore({"anthropic": "sk-test-key-123456789"})
    from solidseas.ai.usage import UsageLedger

    ledger = UsageLedger(str(tmp_path / "usage.json"))
    cases = [
        (AISettings(provider="anthropic", model="test-model"), cloud_ok),
        (AISettings(provider="ollama", model="llama3", ollama_url="http://127.0.0.1:11434"), loopback_ok),
        (AISettings(provider="ollama", model="llama3", ollama_url="http://localhost:11434"), loopback_ok),
        (AISettings(provider="ollama", model="llama3", ollama_url="http://lab.internal:11434"), lab_ok),
    ]
    for settings, allowed in cases:
        factory.reset()
        provider = factory.get_provider(settings, credentials=store, ledger=ledger)
        if allowed:
            assert not isinstance(provider, NoopProvider), (branch, settings.provider, settings.ollama_url)
        else:
            assert isinstance(provider, NoopProvider) and provider.reason == "policy_refused", (
                branch,
                settings,
            )
            assert provider.set_by_administrator and "administrator" in provider.message
    factory.reset()


@pytest.mark.parametrize("branch", list(BRANCHES))
def test_start_run_honours_each_result(branch, policy_reader, tmp_path):
    from solidseas_app.assistant.automatic import RunRefused, start_run

    values, kw = BRANCHES[branch]
    policy_reader(lambda: read_policy(FakeRegistry(values, **kw)))
    automatic_ok = EXPECTED[branch][3]
    target = FakeTarget()
    if automatic_ok:
        run = start_run(target, said_plan(), runs_folder=str(tmp_path))
        run.release()
    else:
        with pytest.raises(RunRefused) as info:
            start_run(target, said_plan(), runs_folder=str(tmp_path))
        assert info.value.code == "policy_refused"
        assert target.calls == [], "nothing else was asked once the policy refused"
