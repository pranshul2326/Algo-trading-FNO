"""Credential and configuration management for the UI.

Two rules this module exists to enforce:

  * Secret values leave the process masked, never in full. The UI shows you which
    credentials are set and the last four characters, nothing more.
  * The .env file is written atomically with owner-only permissions (0600).

Credentials are applied to os.environ as soon as they are saved, so the broker can
be rebuilt without restarting the service.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import workspaces as ws_mod
from .config import Config, Secrets

log = logging.getLogger(__name__)

ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


@dataclass(frozen=True, slots=True)
class CredSpec:
    key: str
    label: str
    group: str
    help: str
    sensitive: bool = True


CREDENTIALS: tuple[CredSpec, ...] = (
    CredSpec(
        "MATHERAN_API_KEY",
        "Saidarshan dashboard password",
        "service",
        "Stops anything else on this machine from calling the API and firing a trade. "
        "Mandatory if you bind to anything other than 127.0.0.1. Stored as "
        "MATHERAN_API_KEY in .env.",
    ),
    CredSpec(
        "DHAN_CLIENT_ID",
        "Dhan client ID",
        "dhan",
        "Your Dhan client code, e.g. 1100003626.",
        sensitive=False,
    ),
    CredSpec(
        "DHAN_ACCESS_TOKEN",
        "Dhan access token",
        "dhan",
        "web.dhan.co -> My Profile -> Access DhanHQ APIs. Valid 24 hours, so expect "
        "to paste a fresh one each trading day.",
    ),
    CredSpec(
        "STOXKART_CLIENT_ID",
        "Stoxkart client ID",
        "stoxkart",
        "Your Stoxkart trading ID.",
        sensitive=False,
    ),
    CredSpec(
        "STOXKART_API_KEY",
        "Stoxkart API key",
        "stoxkart",
        "App key from superrapi.stoxkart.com, or from Stoxkart support.",
    ),
    CredSpec(
        "STOXKART_API_SECRET",
        "Stoxkart API secret",
        "stoxkart",
        "Secret key paired with the app key above.",
    ),
    CredSpec(
        "STOXKART_PASSWORD",
        "Stoxkart password",
        "stoxkart",
        "Used by the Superr login handshake. Leave blank to log in manually.",
    ),
    CredSpec(
        "UPSTOX_ACCESS_TOKEN",
        "Upstox access token (optional)",
        "upstox",
        "Not required. Upstox candles work with no credentials at all; a token only "
        "upgrades the price feed from last-1-minute-close to live tick LTP. Generate "
        "one on the Upstox developer apps page if you want that.",
    ),
)

CREDENTIAL_KEYS = {c.key for c in CREDENTIALS}

GROUPS: dict[str, dict] = {
    "service": {
        "label": "Saidarshan dashboard (not a broker)",
        "requires": ["MATHERAN_API_KEY"],
        "note": "A password you choose, for this app only. It is unrelated to your "
        "broker accounts. Press Generate below and it is saved and applied at once; "
        "read it back any time with: grep MATHERAN_API_KEY .env",
    },
    "dhan": {
        "label": "Dhan (DhanHQ v2)",
        "requires": ["DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"],
        "note": "Order placement also needs a static IP whitelisted on your Dhan account.",
    },
    "stoxkart": {
        "label": "Stoxkart (Superr API)",
        "requires": ["STOXKART_CLIENT_ID", "STOXKART_API_KEY", "STOXKART_API_SECRET"],
        "note": "Adapter is partial: market data falls back to another provider and "
        "live order placement stays disabled until the payload contract is confirmed.",
    },
    "upstox": {
        "label": "Upstox (market data)",
        "requires": [],  # nothing required: candles are unauthenticated
        "note": "Free candles for equities, indices and options with no credentials. "
        "Select it as the data source under Connection.",
    },
}


def mask(value: str | None, sensitive: bool = True) -> str | None:
    """Never return a secret in full."""
    if not value:
        return None
    if not sensitive:
        return value
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * min(12, len(value) - 4) + value[-4:]


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def _quote(value: str) -> str:
    """Quote a .env value only when it needs it."""
    if value == "" or re.search(r"[\s#'\"\\$]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote(value: str) -> str:
    v = value.strip()
    # Strip an inline comment only when the value is not quoted.
    if v[:1] not in {'"', "'"} and "#" in v:
        v = v.split("#", 1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        body = v[1:-1]
        if v[0] == '"':
            body = body.replace('\\"', '"').replace("\\\\", "\\")
        return body
    return v


class EnvFile:
    """Read/write a .env file, preserving unmanaged lines and comments."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        out: dict[str, str] = {}
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = ENV_LINE.match(line)
                if m:
                    out[m.group(1)] = _unquote(m.group(2))
        except OSError as exc:
            log.error("settings: could not read %s: %s", self.path, exc)
        return out

    def write(self, updates: dict[str, str | None]) -> list[str]:
        """Apply updates. A None value removes the key. Returns the keys touched."""
        existing_lines: list[str] = []
        if self.path.exists():
            try:
                existing_lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                log.error("settings: could not read %s: %s", self.path, exc)

        touched: list[str] = []
        seen: set[str] = set()
        out: list[str] = []

        for line in existing_lines:
            m = ENV_LINE.match(line) if line.strip() and not line.lstrip().startswith("#") else None
            if m is None:
                out.append(line)
                continue
            key = m.group(1)
            if key in updates:
                seen.add(key)
                value = updates[key]
                if value is None:
                    touched.append(key)
                    continue  # drop the line
                out.append(f"{key}={_quote(value)}")
                touched.append(key)
            else:
                out.append(line)

        new_keys = [k for k, v in updates.items() if k not in seen and v is not None]
        if new_keys:
            if out and out[-1].strip():
                out.append("")
            out.append("# written by the Saidarshan settings UI")
            for key in new_keys:
                out.append(f"{key}={_quote(updates[key])}")
                touched.append(key)

        self._write_atomic("\n".join(out).rstrip("\n") + "\n")
        return touched

    def _write_atomic(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".env.", suffix=".tmp")
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # 0600 before any content lands
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise


class SettingsManager:
    """Owns the .env and config.yaml files behind the settings UI."""

    def __init__(self, cfg: Config, env_path: Path | None = None,
                 config_path: Path | None = None):
        self.cfg = cfg
        self.env = EnvFile(env_path or Path(".env"))
        self.config_path = Path(config_path or "config.yaml")

    # ---- credentials ----
    def credential_status(self) -> dict:
        stored = self.env.read()
        groups: list[dict] = []
        for name, meta in GROUPS.items():
            specs = [c for c in CREDENTIALS if c.group == name]
            fields = []
            for spec in specs:
                value = os.environ.get(spec.key) or stored.get(spec.key) or ""
                fields.append(
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "help": spec.help,
                        "sensitive": spec.sensitive,
                        "is_set": bool(value),
                        "preview": mask(value, spec.sensitive),
                        "from_env_file": spec.key in stored,
                    }
                )
            required = meta.get("requires", [])
            ready = all(bool(os.environ.get(k) or stored.get(k)) for k in required)
            groups.append(
                {
                    "group": name,
                    "label": meta["label"],
                    "note": meta.get("note", ""),
                    "ready": ready,
                    "required": required,
                    "fields": fields,
                }
            )
        return {
            "env_file": str(self.env.path.resolve()),
            "env_file_exists": self.env.path.exists(),
            "env_file_mode": (
                oct(self.env.path.stat().st_mode & 0o777) if self.env.path.exists() else None
            ),
            "groups": groups,
        }

    def save_credentials(self, values: dict[str, str | None]) -> dict:
        unknown = set(values) - CREDENTIAL_KEYS
        if unknown:
            raise ValueError(f"unknown credential keys: {sorted(unknown)}")

        updates: dict[str, str | None] = {}
        for key, raw in values.items():
            if raw is None:
                updates[key] = None
                continue
            value = str(raw).strip()
            if value == "":
                # An empty string means "leave alone"; use null to clear a value.
                continue
            if "\n" in value or "\r" in value:
                raise ValueError(f"{key} must not contain newlines")
            updates[key] = value

        if not updates:
            return {"saved": [], "cleared": []}

        touched = self.env.write(updates)

        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        self.cfg.secrets = Secrets.from_env()
        saved = [k for k, v in updates.items() if v is not None]
        cleared = [k for k, v in updates.items() if v is None]
        log.info("settings: credentials updated (%s)", ", ".join(touched) or "none")
        return {"saved": saved, "cleared": cleared}

    # ---- config.yaml ----
    def config_snapshot(self) -> dict:
        """Every setting, derived from the dataclasses.

        Deliberately reflective rather than hand-listed: a hand-written version had
        already fallen behind, which silently hid new settings from the UI and made
        them unsavable.
        """
        c = self.cfg
        return {
            "mode": c.mode,
            "broker": _dump(c.broker),
            "server": _dump(c.server),
            "engine": _dump(c.engine),
            "strategy": _dump(c.strategy),
            "risk": _dump(c.risk),
            "options": _dump(c.options),
            "scanner": _dump(c.scanner),
            # Only the parts a workspace saved for itself; the rest follow the
            # sections above (workspaces.py).
            "workspaces": ws_mod.snapshot(c),
            "warmup_bars": c.strategy.warmup_bars(),
            "config_file": str(self.config_path.resolve()),
        }

    def workspace_snapshot(self, workspace: str) -> dict:
        """One workspace's effective strategy, risk and setup defaults, and which of
        them were saved for it rather than followed from the top-level sections."""
        settings = self.cfg.workspace(workspace)
        return {
            "id": workspace,
            "label": ws_mod.label_of(workspace),
            "strategy": _dump(settings.strategy),
            "risk": _dump(settings.risk),
            "defaults": dict(settings.defaults),
            "customised": dict(settings.customised),
            "warmup_bars": settings.strategy.warmup_bars(),
        }

    def update_workspace(self, workspace: str, patch: dict) -> dict:
        """Save strategy / risk / setup defaults for one workspace only.

        The other workspaces and the top-level sections are untouched: each workspace
        holds its own deep copies, so no assignment here can reach another one.
        """
        from .config import validate

        if workspace not in ws_mod.WORKSPACES:
            raise ValueError(f"unknown workspace {workspace!r}")
        unknown = set(patch) - {"strategy", "risk", "defaults"}
        if unknown:
            raise ValueError(f"unknown workspace settings sections: {sorted(unknown)}")
        current = self.cfg.workspace(workspace)
        before = copy.deepcopy(current)
        try:
            for part in ("strategy", "risk"):
                values = patch.get(part)
                if values is None:
                    continue
                obj = getattr(current, part)
                for key, value in values.items():
                    if key not in obj.__dataclass_fields__:
                        raise ValueError(f"unknown {part} setting: {key}")
                    setattr(obj, key, copy.deepcopy(value))
                current.customised[part] = True
            if patch.get("defaults") is not None:
                current.defaults = ws_mod.check_defaults(
                    workspace, patch["defaults"], ws_mod.defaults_schema(self.cfg),
                    base=current.defaults,
                )
                current.customised["defaults"] = True
            validate(self.cfg)
        except Exception:
            self.cfg.workspaces[workspace] = before
            raise
        self.persist_config()
        return self.workspace_snapshot(workspace)

    def reset_workspace(self, workspace: str, parts: list[str]) -> dict:
        """Stop saving the given parts for a workspace: they follow the top-level
        sections again (deep copies, as on first load)."""
        if workspace not in ws_mod.WORKSPACES:
            raise ValueError(f"unknown workspace {workspace!r}")
        bad = set(parts) - {"strategy", "risk", "defaults"}
        if bad or not parts:
            raise ValueError("parts must be any of strategy, risk, defaults")
        current = self.cfg.workspace(workspace)
        for part in parts:
            current.customised[part] = False
        ws_mod.refresh_followers(self.cfg)
        self.persist_config()
        return self.workspace_snapshot(workspace)

    def update_config(self, patch: dict) -> dict:
        """Apply a partial config update, validate it, then persist to config.yaml.

        `strategy` and `risk` here are the top-level sections: legacy watches no
        workspace owns read them, and so does every workspace that has not saved its
        own (refreshed below). That keeps API callers from before workspaces working.
        """
        from .config import validate

        sections = {
            "engine": self.cfg.engine,
            "strategy": self.cfg.strategy,
            "risk": self.cfg.risk,
            "options": self.cfg.options,
            "scanner": self.cfg.scanner,
        }
        before = {name: _dump(obj) for name, obj in sections.items()}
        before_mode = self.cfg.mode
        before_broker = _dump(self.cfg.broker)

        try:
            if "mode" in patch and patch["mode"] is not None:
                self.cfg.mode = str(patch["mode"]).lower()
            if patch.get("broker"):
                name = patch["broker"].get("name")
                if name:
                    self.cfg.broker.name = str(name).lower()
                if "data_broker" in patch["broker"]:
                    raw = patch["broker"]["data_broker"]
                    self.cfg.broker.data_broker = str(raw).lower() if raw else None

            for name, obj in sections.items():
                for key, value in (patch.get(name) or {}).items():
                    if key not in obj.__dataclass_fields__:
                        raise ValueError(f"unknown {name} setting: {key}")
                    setattr(obj, key, value)

            validate(self.cfg)
        except Exception:
            # Roll back everything so a rejected patch cannot leave the engine
            # half-configured. Restoring only some fields once left an invalid
            # data_broker behind after a 400.
            self.cfg.mode = before_mode
            for key, value in before_broker.items():
                setattr(self.cfg.broker, key, value)
            for name, obj in sections.items():
                for key, value in before[name].items():
                    setattr(obj, key, value)
            raise

        # Workspaces that follow the top-level sections pick up the change, as deep
        # copies; a workspace that saved its own keeps it.
        ws_mod.refresh_followers(self.cfg)
        self.persist_config()
        return self.config_snapshot()

    def persist_config(self) -> None:
        snapshot = self.config_snapshot()
        snapshot.pop("warmup_bars", None)
        snapshot.pop("config_file", None)
        if not snapshot.get("workspaces"):
            # Nothing saved per workspace yet: leave config.yaml exactly as before.
            snapshot.pop("workspaces", None)
        # A newer setting left at its default is not written, so the file still loads
        # in a version that does not know the key (config sections refuse unknown keys).
        for section, key in _OMIT_WHEN_NONE:
            if snapshot.get(section, {}).get(key, 0) is None:
                snapshot[section].pop(key)
        text = (
            "# Managed by the Saidarshan settings UI. Secrets live in .env, not here.\n"
            + yaml.safe_dump(snapshot, sort_keys=False, default_flow_style=False)
        )
        fd, tmp = tempfile.mkstemp(dir=str(self.config_path.parent or "."), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.config_path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        log.info("settings: wrote %s", self.config_path)


def _dump(obj) -> dict:
    return {f: getattr(obj, f) for f in obj.__dataclass_fields__}


# (section, key) pairs added after config.yaml files were already in use; see
# persist_config.
_OMIT_WHEN_NONE: tuple[tuple[str, str], ...] = (("strategy", "exit_timeframe_minutes"),)
