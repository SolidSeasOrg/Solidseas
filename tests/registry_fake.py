"""A stand-in for ``HKEY_CURRENT_USER`` with winreg's errors, as ``solidseas.swapi.hkcu`` reads and
writes it: keys are paths, values ``(registry type, data)``, and every write is recorded."""


class FakeRegistry:
    """Keys (paths, their parents made as needed) holding values; ``writes`` lists every write."""

    def __init__(self, values: dict[tuple[str, str], tuple] | None = None, keys=()) -> None:
        self.keys: dict[str, dict[str, tuple]] = {}
        self.writes: list[tuple] = []
        for path in keys:
            self._make(path)
        for (path, name), value in (values or {}).items():
            self._make(path)[name] = value

    def _make(self, path: str) -> dict:
        parts = path.split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:i]), {})
        return self.keys[path]

    def _key(self, path: str) -> dict:
        if path not in self.keys:
            raise FileNotFoundError(path)
        return self.keys[path]

    def subkeys(self, path):
        self._key(path)
        prefix = path + "\\"
        return sorted({k[len(prefix):].split("\\")[0] for k in self.keys if k.startswith(prefix)})

    def values(self, path):
        return dict(self._key(path))

    def value(self, path, name):
        try:
            return self._key(path)[name]
        except KeyError:
            raise FileNotFoundError(f"{path}\\{name}") from None

    def set_value(self, path, name, value):
        self.writes.append(("set", path, name, value))
        self._make(path)[name] = value

    def delete_value(self, path, name):
        self.writes.append(("delete", path, name))
        try:
            del self._key(path)[name]
        except KeyError:
            raise FileNotFoundError(f"{path}\\{name}") from None

    def snapshot(self) -> dict:
        """Every value, by (key path, value name)."""
        return {(k, n): v for k, vals in self.keys.items() for n, v in vals.items()}
