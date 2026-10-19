"""API keys: the Secret that hides itself, the in-memory store, and the Credential Manager
store's ctypes code driven through a stand-in for advapi32. Tests never write the real
Windows Credential Manager; one Windows-only test reads it, at a name that does not exist."""

import ctypes
import pickle
import sys
import uuid

import pytest

from ai_support import KEY
from solidseas.ai import credentials
from solidseas.ai.credentials import (
    CREDENTIALW,
    MemoryCredentialStore,
    Secret,
    UnavailableCredentialStore,
    WindowsCredentialStore,
    target_name,
)
from solidseas.ai.errors import CredentialStoreError, InvalidSettingError

WINDOWS = sys.platform == "win32"


# --------------------------------------------------------------------------- Secret
def test_a_secret_hides_itself():
    s = Secret("  " + KEY + "\n")
    assert s.reveal() == KEY
    for text in (repr(s), str(s), f"{s}", f"{s!r}", repr([s]), repr({"key": s})):
        assert KEY not in text and "hidden" in text
    assert s == Secret(KEY) and s != Secret(KEY + "x") and hash(s) == hash(Secret(KEY))
    assert Secret(s).reveal() == KEY
    with pytest.raises(TypeError):
        pickle.dumps(s)
    with pytest.raises(AttributeError):
        s._value = "x"


@pytest.mark.parametrize(
    "bad", ["", "short", "has space inside", "tab\tkey12345", "\u00e9" * 10, "x" * 1025, None, 12345678]
)
def test_a_secret_must_look_like_a_key(bad):
    with pytest.raises(InvalidSettingError) as info:
        Secret(bad)
    assert str(bad) not in str(info.value) or bad in ("", None)


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "ollama", "a-b_c9"])
def test_target_names(provider):
    assert target_name(provider) == "SolidSeas/" + provider


@pytest.mark.parametrize("provider", ["", "Anthropic", "a/b", "a b", "x" * 33, "../x", None, "9x"])
def test_bad_provider_names_are_refused(provider):
    with pytest.raises(InvalidSettingError):
        target_name(provider)


# --------------------------------------------------------------------------- the stores
def test_the_memory_store():
    store = MemoryCredentialStore({"openai": KEY})
    assert store.is_set("openai") and not store.is_set("anthropic")
    assert store.get("openai").reveal() == KEY and store.get("anthropic") is None
    store.set("anthropic", Secret("sk-ant-test-12345678"))
    assert store.get("anthropic").reveal() == "sk-ant-test-12345678"
    assert store.clear("anthropic") and not store.clear("anthropic")
    assert KEY not in repr(store)


def test_the_unavailable_store_never_holds_a_key():
    store = UnavailableCredentialStore()
    assert store.get("openai") is None and not store.is_set("openai") and not store.clear("openai")
    with pytest.raises(CredentialStoreError):
        store.set("openai", KEY)


def test_the_default_store_in_tests_is_in_memory():
    assert isinstance(credentials.default_store(), MemoryCredentialStore)


# --------------------------------------------------------------------------- Credential Manager, faked
class FakeAdvapi:
    """advapi32's credential functions, in memory, with their calling convention: the
    store copies what CredWriteW is given and hands CredReadW's caller a CREDENTIALW it
    allocated, which CredFree releases."""

    def __init__(self, write_error: int = 0, read_error: int = 0) -> None:
        self.stored: dict[str, dict] = {}
        self.allocated: list = []
        self.freed = 0
        self.write_error = write_error
        self.read_error = read_error
        self._last = 0

    def get_last_error(self) -> int:
        return self._last

    def CredWriteW(self, ref, flags):
        cred = ref._obj
        assert isinstance(cred, CREDENTIALW) and flags == 0
        if self.write_error:
            self._last = self.write_error
            return 0
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        self.stored[cred.TargetName] = {
            "type": cred.Type,
            "persist": cred.Persist,
            "blob": blob,
            "user": cred.UserName,
            "comment": cred.Comment,
        }
        return 1

    def CredReadW(self, name, type_, flags, ref):
        if self.read_error:
            self._last = self.read_error
            return 0
        entry = self.stored.get(name)
        if entry is None or entry["type"] != type_:
            self._last = credentials.ERROR_NOT_FOUND
            return 0
        buffer = (ctypes.c_ubyte * len(entry["blob"])).from_buffer_copy(entry["blob"])
        cred = CREDENTIALW()
        cred.Type, cred.TargetName = type_, name
        cred.CredentialBlobSize = len(entry["blob"])
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        self.allocated.append((cred, buffer))
        ref._obj.contents = cred
        return 1

    def CredDeleteW(self, name, type_, flags):
        if self.stored.pop(name, None) is None:
            self._last = credentials.ERROR_NOT_FOUND
            return 0
        return 1

    def CredFree(self, pointer):
        self.freed += 1


def test_a_key_round_trips_through_credential_manager_calls():
    api = FakeAdvapi()
    store = WindowsCredentialStore(api)
    assert store.get("anthropic") is None and not store.is_set("anthropic")
    store.set("anthropic", KEY)
    entry = api.stored["SolidSeas/anthropic"]
    assert entry["type"] == credentials.CRED_TYPE_GENERIC
    assert entry["persist"] == credentials.CRED_PERSIST_LOCAL_MACHINE, "the key stays on this PC"
    assert entry["blob"] == KEY.encode("utf-16-le") and entry["user"] == "SolidSeas"
    got = store.get("anthropic")
    assert isinstance(got, Secret) and got.reveal() == KEY and store.is_set("anthropic")
    assert api.freed == 1 + 1, "every CredReadW result is freed"
    assert store.clear("anthropic") and not store.clear("anthropic")


def test_credential_manager_errors_never_show_the_key():
    store = WindowsCredentialStore(FakeAdvapi(write_error=1312))
    with pytest.raises(CredentialStoreError) as info:
        store.set("openai", KEY)
    assert "1312" in str(info.value) and KEY not in str(info.value) and "SolidSeas/openai" in str(info.value)
    store = WindowsCredentialStore(FakeAdvapi(read_error=5))
    with pytest.raises(CredentialStoreError) as info:
        store.get("openai")
    assert "error 5" in str(info.value)
    assert not store.is_set("openai")


def test_a_stored_value_that_is_not_a_key_is_reported_not_returned():
    api = FakeAdvapi()
    api.stored["SolidSeas/gemini"] = {
        "type": 1,
        "persist": 2,
        "blob": "not a key".encode("utf-16-le"),
        "user": None,
        "comment": None,
    }
    with pytest.raises(CredentialStoreError) as info:
        WindowsCredentialStore(api).get("gemini")
    assert "not a valid API key" in str(info.value) and "not a key" not in str(info.value)


def test_the_credential_structure_matches_wincred_h():
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(CREDENTIALW) == (80 if pointer == 8 else 52)
    assert CREDENTIALW.CredentialBlob.offset == (40 if pointer == 8 else 28)
    assert CREDENTIALW.UserName.offset == (72 if pointer == 8 else 48)


@pytest.mark.skipif(not WINDOWS, reason="Credential Manager is Windows only")
def test_the_real_store_reads_a_missing_entry_as_none():
    # read only, at a name nothing uses: the real Credential Manager is never written by a test
    assert WindowsCredentialStore().get("test-absent-" + uuid.uuid4().hex[:12]) is None
