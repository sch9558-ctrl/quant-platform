"""Shared Paper Broker implementation (spec section 23).

Simulates fills immediately at a caller-supplied price (this platform has
no live order book), applies the same realistic cost model used by the
backtester, and -- critically -- routes every order through the shared
`RiskManager` before it can increase exposure, exactly like a live broker
adapter would need to (spec section 17: "모든 Paper/Live 주문은 반드시
Risk Manager를 통과해야 한다"). State (cash, positions, fill history, daily
equity) persists to a small JSON file so a paper-trading track record
survives across CLI runs.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd

from quant import config
from quant.backtest.costs import CostModel
from quant.broker.base import BrokerInterface, Fill, OrderRejection, Position
from quant.risk.manager import PortfolioState, RiskManager


class PaperBrokerBase(BrokerInterface):
    is_live = False

    def __init__(
        self,
        market: str,
        initial_capital: float,
        state_path: Path | None = None,
        risk_manager: RiskManager | None = None,
    ):
        self.market = market
        self.cost_model = CostModel(market)
        self.risk_manager = risk_manager or RiskManager()
        self.state_path = state_path or (
            config.resolve_path(config.settings()["paths"]["db_dir"]) / f"paper_{market}.json"
        )
        self.initial_capital = initial_capital
        self._load_or_init()

    # -- persistence --------------------------------------------------
    def _load_or_init(self) -> None:
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            self.cash = data["cash"]
            self.positions = {s: Position(**p) for s, p in data["positions"].items()}
            self.fills = [
                Fill(**{**f, "filled_at": pd.Timestamp(f["filled_at"])}) for f in data["fills"]
            ]
            self.equity_history = [(pd.Timestamp(e["date"]), e["equity"]) for e in data["equity_history"]]
            self.peak_nav = data.get("peak_nav", self.initial_capital)
            self.consecutive_losses = data.get("consecutive_losses", 0)
        else:
            self.cash = self.initial_capital
            self.positions: dict[str, Position] = {}
            self.fills: list[Fill] = []
            self.equity_history: list[tuple[pd.Timestamp, float]] = []
            self.peak_nav = self.initial_capital
            self.consecutive_losses = 0
            self._save()

    def _save(self) -> None:
        data = {
            "cash": self.cash,
            "positions": {s: {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost}
                          for s, p in self.positions.items()},
            "fills": [
                {"fill_id": f.fill_id, "symbol": f.symbol, "side": f.side, "quantity": f.quantity,
                 "price": f.price, "commission": f.commission, "tax_or_fee": f.tax_or_fee,
                 "filled_at": f.filled_at.isoformat(), "reason": f.reason}
                for f in self.fills
            ],
            "equity_history": [{"date": d.isoformat(), "equity": e} for d, e in self.equity_history],
            "peak_nav": self.peak_nav,
            "consecutive_losses": self.consecutive_losses,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, indent=2))

    def reset(self) -> None:
        """Wipe paper-trading state back to a fresh starting balance."""
        if self.state_path.exists():
            self.state_path.unlink()
        self._load_or_init()

    # -- BrokerInterface ------------------------------------------------
    def get_cash(self) -> float:
        return self.cash

    def get_positions(self) -> dict[str, Position]:
        return dict(self.positions)

    def get_account_value(self, prices: dict[str, float] | None = None) -> float:
        value = self.cash
        for sym, pos in self.positions.items():
            price = (prices or {}).get(sym, pos.avg_cost)
            value += pos.quantity * price
        return value

    def submit_order(
        self, symbol: str, side: str, quantity: float, price: float, sector: str | None = None,
        reason: str = "manual",
    ) -> Fill | OrderRejection:
        if quantity <= 0 or price <= 0:
            return OrderRejection(symbol, quantity, ["invalid quantity or price"])

        nav = self.get_account_value({symbol: price})
        if nav <= 0:
            return OrderRejection(symbol, quantity, ["account value is zero or negative"])

        current_pos = self.positions.get(symbol, Position(symbol, 0.0, 0.0))
        signed_requested = quantity if side == "buy" else -quantity
        requested_new_qty = current_pos.quantity + signed_requested
        target_weight = max(requested_new_qty * price / nav, 0.0)

        current_weights = {
            s: (p.quantity * price / nav if s == symbol else p.quantity * p.avg_cost / nav)
            for s, p in self.positions.items()
        }
        returns_history = self._recent_return_history()
        state = PortfolioState(
            nav=nav, peak_nav=self.peak_nav, positions=current_weights,
            daily_pnl_pct=self._last_daily_return(), consecutive_losses=self.consecutive_losses,
            returns_history=returns_history,
        )
        check = self.risk_manager.check_order(symbol, target_weight, state, sector=sector)

        approved_new_qty = check.approved_weight * nav / price
        actual_delta = approved_new_qty - current_pos.quantity

        if side == "buy" and actual_delta <= 1e-9:
            return OrderRejection(symbol, quantity, check.reasons or ["risk manager reduced order size to zero"])
        if side == "sell":
            actual_delta = -quantity  # risk manager never blocks reducing/exiting a position

        notional = abs(actual_delta) * price
        is_sell = actual_delta < 0
        fill_cost = self.cost_model.apply(notional, is_sell=is_sell, asset_type="equity", exchange=None)

        new_qty = current_pos.quantity + actual_delta
        if actual_delta > 0:
            new_avg_cost = (
                (current_pos.quantity * current_pos.avg_cost + actual_delta * price) / new_qty
                if new_qty > 0 else 0.0
            )
        else:
            new_avg_cost = current_pos.avg_cost

        if is_sell:
            self.cash += notional - fill_cost.total_cost
        else:
            self.cash -= notional + fill_cost.total_cost

        if abs(new_qty) < 1e-9:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = Position(symbol=symbol, quantity=new_qty, avg_cost=new_avg_cost)

        fill = Fill(
            fill_id=uuid.uuid4().hex[:12], symbol=symbol, side="sell" if is_sell else "buy",
            quantity=abs(actual_delta), price=price, commission=fill_cost.commission,
            tax_or_fee=fill_cost.tax_or_fee, filled_at=pd.Timestamp.now(), reason=reason,
        )
        self.fills.append(fill)
        self._save()
        return fill

    def rebalance_to_target_weights(
        self, target_weights: dict[str, float], prices: dict[str, float], sectors: dict[str, str] | None = None,
    ) -> list[Fill | OrderRejection]:
        """Convenience: given a target weight per symbol and current prices,
        compute and submit the buy/sell orders needed to get there from the
        current portfolio (spec section 23: apply scanner/portfolio-engine
        output directly)."""
        sectors = sectors or {}
        nav = self.get_account_value(prices)
        results: list[Fill | OrderRejection] = []

        all_symbols = set(target_weights) | set(self.positions)
        for symbol in all_symbols:
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue
            target_qty = (target_weights.get(symbol, 0.0) * nav) / price
            current_qty = self.positions.get(symbol, Position(symbol, 0.0, 0.0)).quantity
            delta = target_qty - current_qty
            if abs(delta * price) < 1.0:  # skip dust-sized rebalances
                continue
            side = "buy" if delta > 0 else "sell"
            results.append(self.submit_order(symbol, side, abs(delta), price, sector=sectors.get(symbol), reason="rebalance"))
        return results

    def get_fill_history(self) -> list[Fill]:
        return list(self.fills)

    def record_daily_equity(self, prices: dict[str, float], as_of: pd.Timestamp | None = None) -> float:
        as_of = as_of or pd.Timestamp.today().normalize()
        equity = self.get_account_value(prices)
        prev_equity = self.equity_history[-1][1] if self.equity_history else self.initial_capital
        self.equity_history.append((as_of, equity))
        self.peak_nav = max(self.peak_nav, equity)
        if equity < prev_equity:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self._save()
        return equity

    def get_equity_curve(self) -> pd.Series:
        if not self.equity_history:
            return pd.Series(dtype=float)
        dates, values = zip(*self.equity_history)
        return pd.Series(values, index=pd.DatetimeIndex(dates), name="equity").sort_index()

    def _last_daily_return(self) -> float:
        curve = self.get_equity_curve()
        if len(curve) < 2:
            return 0.0
        return float(curve.iloc[-1] / curve.iloc[-2] - 1)

    def _recent_return_history(self) -> dict[str, pd.Series]:
        # paper broker doesn't hold full OHLCV history itself -- correlation
        # checks with real return series should be supplied by the caller
        # via a subclass/wrapper if needed. Kept empty here by default.
        return {}
