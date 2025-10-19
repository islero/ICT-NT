# shared_state.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Dict, Iterable, Mapping, Optional
import json
from decimal import Decimal
from datetime import datetime, date, time
from pathlib import Path

@dataclass
class SharedState:
    """
    Centralized, shared, mutable state for rules and strategy.

    - Holds a single dictionary (data) shared by all rules.
    - Provides small helpers (set_flag, clear_keys, snapshot) to reduce boilerplate.
    - Optional thread-safety via RLock (useful if you later introduce concurrency).
    """
    _data_dict: Dict[str, Any] = field(default_factory=dict)
    _lock: Optional[RLock] = field(default_factory=RLock)

    # ---------- core API ----------
    def set(self, key: str, value: Any) -> None:
        """Set any value under the given key."""
        k = _key_of(key)
        if self._lock:  # simple, low-cost guard
            with self._lock:
                self._data_dict[k] = value
        else:
            self._data_dict[k] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value or default if not present."""
        k = _key_of(key)
        if self._lock:
            with self._lock:
                return self._data_dict.get(k, default)
        return self._data_dict.get(k, default)

    def pop(self, key: Any, default: Any = None) -> Any:
        """Pop a value under a key, returning default if absent."""
        k = _key_of(key)
        if self._lock:
            with self._lock:
                return self._data_dict.pop(k, default)
        return self._data_dict.pop(k, default)

    def update(self, other: Mapping[str, Any]) -> None:
        """Bulk update of key-value pairs."""
        if self._lock:
            with self._lock:
                self._data_dict.update(other)
        else:
            self._data_dict.update(other)

    def clear_keys(self, *keys: Iterable[str]) -> None:
        """Remove multiple keys if present."""
        flat_keys = []
        for x in keys:
            if isinstance(x, (list, tuple, set)):
                flat_keys.extend(x)
            else:
                flat_keys.append(x)
        if self._lock:
            with self._lock:
                for k in flat_keys:
                    self._data_dict.pop(_key_of(k), None)
        else:
            for k in flat_keys:
                self._data_dict.pop(_key_of(k), None)

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy (useful for logging or tests)."""
        if self._lock:
            with self._lock:
                return dict(self._data_dict)
        return dict(self._data_dict)

    def __contains__(self, key: str) -> bool:
        k = _key_of(key)
        if self._lock:
            with self._lock:
                return k in self._data_dict
        return k in self._data_dict

    def _to_jsonable(self, obj: Any) -> Any:
        """Best-effort conversion of arbitrary objects to JSON-serializable form.

        - Handles primitives, Enum (uses `.value` if simple), Decimal (as str),
          datetimes (ISO 8601), containers (dict/list/tuple/set), and tries
          common hooks like `.to_dict()`, `.to_json()`, `.to_str()`, or `.value`.
        - Falls back to `str(obj)` for unknown types (e.g., Cython cdef objects),
          which avoids pickle errors like "@auto_pickle(True)".
        """
        # primitives
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj

        # enums → simple value or string
        if isinstance(obj, Enum):
            v = getattr(obj, "value", None)
            return v if isinstance(v, (bool, int, float, str)) else str(obj)

        # decimals → string to avoid precision loss in JSON
        if isinstance(obj, Decimal):
            return str(obj)

        # datetimes → ISO 8601
        if isinstance(obj, (datetime, date, time)):
            try:
                return obj.isoformat()
            except Exception:
                return str(obj)

        # dict → recurse on keys/values
        if isinstance(obj, dict):
            return {str(self._to_jsonable(k)): self._to_jsonable(v) for k, v in obj.items()}

        # sequences/sets → list
        if isinstance(obj, (list, tuple, set)):
            return [self._to_jsonable(v) for v in obj]

        # try common conversion hooks
        for attr in ("to_dict", "to_json", "to_str"):
            fn = getattr(obj, attr, None)
            if callable(fn):
                try:
                    val = fn()
                    if attr == "to_json" and isinstance(val, str):
                        try:
                            return json.loads(val)
                        except Exception:
                            return val
                    return self._to_jsonable(val)
                except Exception:
                    pass

        # value attribute (e.g., identifiers)
        v = getattr(obj, "value", None)
        if v is not None:
            return self._to_jsonable(v)

        # last resort
        return str(obj)

    # ---------- legacy bridge ----------
    @property
    def data_dict(self) -> Dict[str, Any]:
        """
        Backward-compatible reference for legacy code that expects a raw dict.
        NOTE: This is a direct reference to the underlying dict (mutations apply).
        """
        return self._data_dict

    def save_to_redis(
        self,
        key: str = "wyckoff:shared_state:pickle",
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 1,
        password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """
        Serialize and save shared state to Redis.

        Parameters
        ----------
        key : str
            Redis key to save under.
        host : str
            Redis host.
        port : int
            Redis port.
        db : int
            Redis logical database index.
        password : str | None
            Optional Redis password (if your server requires authentication).
        timeout : float | None
            Optional socket timeout for the Redis client.

        Notes
        -----
        As of this implementation, data is stored as JSON (UTF-8). This avoids
        pickling Cython objects (e.g., Nautilus internals) that would raise
        errors like "@auto_pickle(True)". Older pickle payloads are still loaded
        by `load_from_redis` via a pickle fallback.
        """
        import redis
        # Take a snapshot and convert to JSON-safe structure to avoid pickle errors
        data = self.snapshot()
        safe = self._to_jsonable(data)
        payload = json.dumps(safe, ensure_ascii=False).encode("utf-8")
        client = redis.Redis(host=host, port=port, db=db, password=password, socket_timeout=timeout)
        client.set(key, payload)

    def save(self, path: str = "shared_state.json") -> None:
        """Save the entire shared state to the filesystem as JSON.

        Parameters
        ----------
        path : str
            Target file path (relative or absolute). Defaults to "shared_state.json"
            in the current working directory.
        """
        # Take a snapshot and convert to JSON-safe structure
        data = self.snapshot()
        safe = self._to_jsonable(data)

        p = Path(path)
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)

        with p.open("w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False)

    def load(self, path: str = "shared_state.json") -> bool:
        """Load shared state from a JSON file on the filesystem.

        Parameters
        ----------
        path : str
            Source file path. Defaults to "shared_state.json" in the current
            working directory.

        Returns
        -------
        bool
            True if the file existed and state was loaded; False if the file
            was missing.
        """
        p = Path(path)
        if not p.exists():
            return False

        raw = p.read_bytes()

        # Try JSON first
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            # Fallback to legacy pickle payloads if any exist
            import pickle
            data = pickle.loads(raw)

        if not isinstance(data, dict):
            raise ValueError("SharedState load: payload is not a dict")

        # Replace internal dict atomically under the class lock
        if self._lock:
            with self._lock:
                self._data_dict.clear()
                self._data_dict.update(data)
        else:
            self._data_dict.clear()
            self._data_dict.update(data)
        return True

    def load_from_redis(
        self,
        key: str = "wyckoff:shared_state:pickle",
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 1,
        password: str | None = None,
        timeout: float | None = None,
    ) -> bool:
        """
        Load shared state from Redis.

        Parameters
        ----------
        key : str
            Redis key to load from.
        host : str
            Redis host.
        port : int
            Redis port.
        db : int
            Redis logical database index.
        password : str | None
            Optional Redis password (if your server requires authentication).
        timeout : float | None
            Optional socket timeout for the Redis client.
        """
        import redis, json
        client = redis.Redis(host=host, port=port, db=db, password=password, socket_timeout=timeout)
        raw = client.get(key)
        if raw is None:
            return False

        # Try JSON first
        data: Dict[str, Any]
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            # Fallback to legacy pickle payloads if any exist
            import pickle
            data = pickle.loads(raw)

        if not isinstance(data, dict):
            raise ValueError("SharedState load_from_redis: payload is not a dict")

        # Replace internal dict atomically under the class lock
        if self._lock:
            with self._lock:
                self._data_dict.clear()
                self._data_dict.update(data)
        else:
            self._data_dict.clear()
            self._data_dict.update(data)
        return True

def _key_of(key: Any) -> str:
    """
    Normalizes a key to a string. Supports StrEnum/Enum or plain strings.
    """
    if isinstance(key, Enum):
        return str(key.value)
    return str(key)