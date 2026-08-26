"""Strategy registry: instantiate strategies by id from
config/strategies.yaml, so the Research Engine can iterate "every enabled
strategy" without hardcoding a Python list anywhere (spec section 7).
"""
from __future__ import annotations

import importlib

from quant import config
from quant.strategy.base import BaseStrategy

_MODULE_PREFIX = "quant.strategy"


def build_strategy(strategy_id: str, params: dict | None = None) -> BaseStrategy:
    specs = {s["id"]: s for s in config.strategies_config()["strategies"]}
    if strategy_id not in specs:
        raise KeyError(f"Unknown strategy id: {strategy_id!r}. Known: {sorted(specs)}")
    spec = specs[strategy_id]
    module = importlib.import_module(f"{_MODULE_PREFIX}.{spec['module']}")
    cls = getattr(module, spec["class"])
    final_params = {**spec.get("default_params", {}), **(params or {})}
    return cls(**final_params)


def enabled_strategy_ids() -> list[str]:
    return [s["id"] for s in config.strategies_config()["strategies"] if s.get("enabled", True)]


def all_strategy_specs() -> list[dict]:
    return list(config.strategies_config()["strategies"])


def param_grid_for(strategy_id: str) -> dict:
    specs = {s["id"]: s for s in config.strategies_config()["strategies"]}
    return specs[strategy_id].get("param_grid", {})


def build_all_enabled() -> dict[str, BaseStrategy]:
    return {sid: build_strategy(sid) for sid in enabled_strategy_ids()}
