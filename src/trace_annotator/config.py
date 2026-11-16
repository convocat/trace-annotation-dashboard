"""Configuration — reads `.trace-dashboard.yml` from a project root.

Resolution order:
  1. Path passed explicitly to `load_config(path)`.
  2. $TRACE_DASHBOARD_CONFIG env var.
  3. `.trace-dashboard.yml` in the current working directory.
  4. `.trace-dashboard.yml` walked up the directory tree (git-style).
  5. Defaults — no config needed if the repo has `testannotaties/*.xlsx` and
     a Langfuse env is set.

Missing-field philosophy: any top-level block is optional; the loader only
instantiates sources that are actually configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .pii.filter import Locale, PIIFilter, PIIMode


@dataclass
class LangfuseConfig:
    host: str = ""
    project_id: str | None = None
    dataset: str | None = None
    tags: list[str] = field(default_factory=list)
    environment: str | None = None
    limit: int = 100  # Cloud-friendly default (one page). Raise for self-hosted.
    tls_verify: bool = True


@dataclass
class ExcelConfig:
    path: str = ""
    schemas: dict[str, dict] = field(default_factory=dict)


@dataclass
class PIIConfig:
    mode: PIIMode = PIIMode.STRICT
    locales: frozenset[Locale] = field(default_factory=lambda: frozenset({Locale.ANY, Locale.NL}))
    replacement: str = "[{type}]"
    enabled_patterns: frozenset[str] | None = None

    def build(self) -> PIIFilter:
        return PIIFilter(
            mode=self.mode,
            locales=self.locales,
            replacement=self.replacement,
            enabled_patterns=self.enabled_patterns,
        )


@dataclass
class AppConfig:
    project_name: str = "trace-annotation-dashboard"
    source: str = "langfuse"  # "langfuse" | "excel"
    port: int = 5000
    host: str = "127.0.0.1"
    open_browser: bool = True
    annotations_path: str = "annotations.xlsx"
    cache_size: int = 500

    langfuse: LangfuseConfig = field(default_factory=LangfuseConfig)
    excel: ExcelConfig = field(default_factory=ExcelConfig)
    pii: PIIConfig = field(default_factory=PIIConfig)


# --- Loading ----------------------------------------------------------------

CONFIG_FILENAME = ".trace-dashboard.yml"


def load_config(explicit_path: Path | str | None = None) -> AppConfig:
    """Resolve and parse config. Returns defaults if no file is found.

    Also loads `.env` from the config's directory (or cwd if no config found)
    so credentials like LANGFUSE_PUBLIC_KEY land in the environment before
    loaders look them up. Existing env vars are NOT overridden — explicit shell
    exports win over .env entries.
    """
    path = _resolve_path(explicit_path)
    base_dir = path.parent if path else Path.cwd()

    # Load .env from the project root (where the config lives). Silent if missing.
    env_path = base_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    if path is None:
        return AppConfig()

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _parse(raw, base_dir=base_dir)


def _resolve_path(explicit: Path | str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None

    env_path = os.getenv("TRACE_DASHBOARD_CONFIG")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.exists():
            return candidate

    return None


def _parse(raw: dict[str, Any], base_dir: Path) -> AppConfig:
    cfg = AppConfig()

    # Top-level flat fields
    if (v := raw.get("project_name")) is not None:
        cfg.project_name = str(v)
    if (v := raw.get("source")) is not None:
        cfg.source = str(v).lower()
    if (v := raw.get("port")) is not None:
        cfg.port = int(v)
    if (v := raw.get("host")) is not None:
        cfg.host = str(v)
    if (v := raw.get("open_browser")) is not None:
        cfg.open_browser = bool(v)
    if (v := raw.get("cache_size")) is not None:
        cfg.cache_size = int(v)

    # Annotations output path — resolved relative to the config file's dir
    annotations = raw.get("annotations") or {}
    if "path" in annotations:
        cfg.annotations_path = str(_resolve_rel(annotations["path"], base_dir))
    else:
        cfg.annotations_path = str(base_dir / cfg.annotations_path)

    # Langfuse block
    lf = raw.get("langfuse") or {}
    if lf:
        cfg.langfuse = LangfuseConfig(
            host=str(lf.get("host", "")),
            project_id=lf.get("project_id"),
            dataset=lf.get("dataset"),
            tags=list(lf.get("tags") or []),
            environment=lf.get("environment"),
            limit=int(lf.get("limit", 100)),
            tls_verify=bool(lf.get("tls_verify", True)),
        )

    # Excel block
    xl = raw.get("excel") or {}
    if xl:
        cfg.excel = ExcelConfig(
            path=str(_resolve_rel(xl.get("path", ""), base_dir)) if xl.get("path") else "",
            schemas=dict(xl.get("schemas") or {}),
        )

    # PII block
    pii = raw.get("pii_filter") or {}
    if pii:
        mode_s = str(pii.get("mode", "strict")).lower()
        try:
            mode = PIIMode(mode_s)
        except ValueError:
            mode = PIIMode.STRICT

        loc_list = pii.get("locales") or ["any", "nl"]
        locales = frozenset(Locale(l.lower()) for l in loc_list if _is_valid_locale(l))

        replacement = str(pii.get("replacement", "[{type}]"))
        enabled = pii.get("patterns")
        enabled_patterns = frozenset(enabled) if enabled else None

        cfg.pii = PIIConfig(
            mode=mode,
            locales=locales,
            replacement=replacement,
            enabled_patterns=enabled_patterns,
        )

    return cfg


def _resolve_rel(p: str | Path, base_dir: Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _is_valid_locale(value: Any) -> bool:
    try:
        Locale(str(value).lower())
        return True
    except ValueError:
        return False
