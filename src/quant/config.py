"""Central configuration loader.

Loads every YAML file under `config/` and exposes them as plain dicts, plus
resolves a few important paths and safety switches.

SAFETY: `LIVE_TRADING` is hardcoded to False here. Nothing else in this
module, or in config/settings.yaml, or in the .env file, can turn it True by
itself -- see the docstring on `is_live_trading_enabled()` below.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
    pass

# repo root = two levels up from this file (src/quant/config.py -> repo/)
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

# ---------------------------------------------------------------------------
# Hard safety switch. This constant is the single source of truth. It is
# intentionally NOT read from a config file, so that no YAML edit can ever
# flip it. Changing this requires a human to edit this line of source code.
# ---------------------------------------------------------------------------
_LIVE_TRADING_HARD_LOCK = False


def is_live_trading_enabled() -> bool:
    """Whether live (real-money) trading is enabled anywhere in this app.

    Two independent locks both must be open for this to return True:
      1. `_LIVE_TRADING_HARD_LOCK` in this file, which a human must edit.
      2. The `LIVE_TRADING` environment variable must also be "true".

    In the shipped state, lock #1 is always False, so this function always
    returns False regardless of environment variables or config files. This
    is intentional and should not be "fixed" by editing config alone.
    """
    env_flag = os.environ.get("LIVE_TRADING", "false").strip().lower() == "true"
    return bool(_LIVE_TRADING_HARD_LOCK and env_flag)


@functools.lru_cache(maxsize=None)
def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def settings() -> dict[str, Any]:
    return _load_yaml("settings.yaml")


def universe_config(market: str) -> dict[str, Any]:
    market = market.lower()
    if market not in ("korea", "us"):
        raise ValueError(f"Unknown market: {market}")
    return _load_yaml(f"universe_{'kr' if market == 'korea' else 'us'}.yaml")


def costs_config() -> dict[str, Any]:
    return _load_yaml("costs.yaml")


def risk_config() -> dict[str, Any]:
    return _load_yaml("risk.yaml")


def ranking_config() -> dict[str, Any]:
    return _load_yaml("ranking.yaml")


def regime_config() -> dict[str, Any]:
    return _load_yaml("regime.yaml")


def validation_config() -> dict[str, Any]:
    return _load_yaml("validation.yaml")


def portfolio_config() -> dict[str, Any]:
    return _load_yaml("portfolio.yaml")


def strategies_config() -> dict[str, Any]:
    return _load_yaml("strategies.yaml")


def resolve_path(relative: str) -> Path:
    """Resolve a path from settings.yaml's `paths` section relative to repo root."""
    p = Path(relative)
    return p if p.is_absolute() else REPO_ROOT / p


def ensure_dirs() -> None:
    """Create all data/log/report directories referenced in settings.yaml."""
    s = settings()
    for key in ("data_raw", "data_processed", "data_cache", "db_dir", "reports_dir", "logs_dir"):
        resolve_path(s["paths"][key]).mkdir(parents=True, exist_ok=True)
