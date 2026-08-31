from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Sequence

import rareiq.trading.config as trading_config_module
from rareiq.trading.backtest import Backtester
from rareiq.trading.broker import AlpacaCredentials, AlpacaPaperClient, BrokerError
from rareiq.trading.config import TradingConfig, TradingConfigError
from rareiq.trading.data import load_bars_csv, save_bars_csv
from rareiq.trading.engine import PaperTradingEngine
from rareiq.trading.risk import TradingStateStore


REPORT_SCHEMA_VERSION = 1


def _date_start(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO date or timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _date_end(value: str) -> datetime:
    parsed = _date_start(value)
    if "T" not in value:
        parsed = datetime.combine(parsed.date(), time.max, tzinfo=timezone.utc)
    return parsed


def _json_print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _load_config(path: str) -> TradingConfig:
    return TradingConfig.load(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rareiq.trading",
        description="Paper-first RareIQ trading research lab (no live mode)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate safety limits")
    validate.add_argument("--config", default="trading_config.example.json")

    download = subparsers.add_parser(
        "download", help="download adjusted Alpaca daily bars"
    )
    download.add_argument("--config", default="trading_config.example.json")
    download.add_argument("--start", required=True, type=_date_start)
    download.add_argument("--end", type=_date_end, default=datetime.now(timezone.utc))
    download.add_argument("--output", required=True)

    backtest = subparsers.add_parser(
        "backtest", help="run next-session base and stress simulations"
    )
    backtest.add_argument("--config", default="trading_config.example.json")
    backtest.add_argument("--csv", required=True)
    backtest.add_argument("--input-metadata")
    backtest.add_argument("--report")
    backtest.add_argument("--include-equity-curve", action="store_true")

    paper = subparsers.add_parser(
        "paper", help="plan, or explicitly submit, one Alpaca paper order"
    )
    paper.add_argument("--config", required=True)
    paper.add_argument("--submit-paper-order", action="store_true")

    state = subparsers.add_parser("show-state", help="show local halt/idempotency state")
    state.add_argument("--config", required=True)

    halt = subparsers.add_parser(
        "kill-switch", help="cancel all paper orders and block new risk"
    )
    halt.add_argument("--config", default="trading_config.json")

    return parser


def _config_hash(config: TradingConfig) -> str:
    encoded = json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _aware_metadata_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"bar provenance {field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"bar provenance {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"bar provenance {field} must be timezone-aware")
    return parsed


def _implementation_hash() -> str:
    digest = hashlib.sha256()
    package_directory = Path(__file__).resolve().parent
    for source_path in sorted(package_directory.glob("*.py")):
        digest.update(source_path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _best_effort_event(
    store: TradingStateStore, event: dict[str, object]
) -> bool:
    try:
        store.append_event(event)
    except (OSError, RuntimeError):
        return False
    return True


def _kill_switch(config_path: str) -> int:
    canonical_runtime = (
        Path(trading_config_module.PROJECT_ROOT) / "runtime" / "trading"
    ).resolve()
    store = TradingStateStore(canonical_runtime)
    latch_error = ""
    try:
        store.latch_kill_switch()
    except (OSError, RuntimeError) as exc:
        latch_error = type(exc).__name__
    _best_effort_event(store, {"type": "manual_kill_switch_requested"})

    supplied_config_hash: str | None = None
    config_load_error = ""
    try:
        supplied_config_hash = _config_hash(TradingConfig.load(config_path))
    except (TradingConfigError, ValueError, OSError) as exc:
        config_load_error = type(exc).__name__

    try:
        binding = store.load_binding()
        if binding is None:
            raise BrokerError(
                "kill switch requested, but no immutable broker account binding exists"
            )
        credentials = AlpacaCredentials.from_environment()
        with AlpacaPaperClient(credentials) as client:
            account = client.get_account()
            broker_account_id = str(account.get("id") or "").strip()
            if not broker_account_id:
                raise BrokerError("broker account response is missing its account ID")
            if broker_account_id != binding["broker_account_id"]:
                raise BrokerError(
                    "paper credentials belong to a different broker account"
                )
            try:
                immediate_cancellations = client.cancel_all_orders()
                immediate_remaining = client.get_open_orders()
                _best_effort_event(
                    store,
                    {
                        "type": "manual_kill_switch_immediate_cancel",
                        "cancel_responses": len(immediate_cancellations),
                        "remaining_open_orders": len(immediate_remaining),
                    },
                )
            except (BrokerError, RuntimeError) as exc:
                immediate_cancellations = []
                _best_effort_event(
                    store,
                    {
                        "type": "manual_kill_switch_immediate_cancel_failed",
                        "reason": str(exc),
                    },
                )
            with store.execution_guard(wait_seconds=55.0):
                final_cancellations = client.cancel_all_orders()
                failed = []
                for item in final_cancellations:
                    try:
                        status = int(item.get("status") or 0)
                    except (TypeError, ValueError):
                        status = 0
                    if status < 200 or status >= 300:
                        failed.append(item)
                remaining = client.get_open_orders()
                positions = client.get_positions()
            cancellations = [*immediate_cancellations, *final_cancellations]
    except (BrokerError, RuntimeError) as exc:
        _best_effort_event(
            store,
            {"type": "paper_cancel_verification_failed", "reason": str(exc)},
        )
        raise BrokerError(
            "kill switch request is retained locally when possible, but broker "
            "cancellation could not be verified"
        ) from exc

    if failed or remaining:
        _best_effort_event(
            store,
            {
                "type": "paper_cancel_verification_failed",
                "failed_responses": len(failed),
                "remaining_open_orders": len(remaining),
            },
        )
        raise BrokerError(
            "kill switch request is retained locally, but paper orders remain unverified"
        )

    residual_positions: list[dict[str, object]] = []
    for item in positions:
        try:
            quantity = float(item["qty"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerError(
                "kill switch canceled orders, but broker positions are unreadable"
            ) from exc
        if not math.isfinite(quantity):
            raise BrokerError(
                "kill switch canceled orders, but broker positions are invalid"
            )
        if abs(quantity) > 1e-9:
            residual_positions.append(
                {"symbol": str(item.get("symbol") or ""), "qty": quantity}
            )

    config_changed = (
        supplied_config_hash is None
        or binding["paper_config_sha256"] != supplied_config_hash
    )
    if residual_positions:
        _best_effort_event(
            store,
            {
                "type": "manual_kill_switch_orders_canceled_positions_remain",
                "cancel_responses": len(cancellations),
                "positions": residual_positions,
                "configuration_changed": config_changed,
                "config_load_error": config_load_error,
            },
        )
        raise BrokerError(
            "kill switch canceled all paper orders, but positions remain; "
            "the command does not flatten holdings automatically"
        )
    if latch_error:
        raise BrokerError(
            "paper orders were canceled, but the local kill-switch sentinel could not be written"
        )

    journal_recorded = _best_effort_event(
        store,
        {
            "type": "manual_kill_switch_verified",
            "cancel_responses": len(cancellations),
            "positions_remaining": 0,
            "configuration_changed": config_changed,
            "config_load_error": config_load_error,
        },
    )
    _json_print(
        {
            "halted": True,
            "reason": "manual_kill_switch",
            "cancel_responses": len(cancellations),
            "remaining_open_orders": 0,
            "positions_remaining": 0,
            "positions_flat": True,
            "configuration_changed": config_changed,
            "journal_recorded": journal_recorded,
        }
    )
    return 0


def _backtest(args: argparse.Namespace, config: TradingConfig) -> dict[str, object]:
    csv_path = Path(args.csv)
    metadata_path = (
        Path(args.input_metadata)
        if args.input_metadata
        else Path(f"{csv_path}.meta.json")
    )
    try:
        input_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"bar provenance metadata not found: {metadata_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid bar provenance metadata: {metadata_path}") from exc
    if not isinstance(input_metadata, dict):
        raise ValueError("bar provenance metadata root must be an object")
    try:
        csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise ValueError(f"bar CSV not found: {csv_path}") from exc
    schema_version = input_metadata.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        raise ValueError("bar provenance requires schema_version=1")
    if input_metadata.get("source") != "alpaca_market_data_api":
        raise ValueError("bar provenance source is not a registered provider")
    if str(input_metadata.get("symbol") or "").upper() != config.symbol:
        raise ValueError("bar provenance symbol does not match the configured symbol")
    if input_metadata.get("feed") != config.data_feed:
        raise ValueError("bar provenance feed does not match the configured feed")
    if input_metadata.get("timeframe") != "1Day":
        raise ValueError("bar provenance timeframe must be 1Day")
    declared_hash = input_metadata.get("csv_sha256")
    if (
        not isinstance(declared_hash, str)
        or len(declared_hash) != 64
        or any(character not in "0123456789abcdef" for character in declared_hash)
    ):
        raise ValueError("bar provenance csv_sha256 must be lowercase hexadecimal")
    if input_metadata.get("csv_sha256") != csv_sha256:
        raise ValueError("bar CSV hash does not match its provenance metadata")
    if input_metadata.get("adjustment") != "all":
        raise ValueError("Alpaca bar provenance must declare adjustment=all")
    requested_start = _aware_metadata_time(
        input_metadata.get("requested_start"), "requested_start"
    )
    requested_end = _aware_metadata_time(
        input_metadata.get("requested_end"), "requested_end"
    )
    first_bar = _aware_metadata_time(input_metadata.get("first_bar"), "first_bar")
    last_bar = _aware_metadata_time(input_metadata.get("last_bar"), "last_bar")
    _aware_metadata_time(input_metadata.get("generated_at"), "generated_at")
    if requested_start > requested_end:
        raise ValueError("bar provenance requested range is reversed")
    bars = load_bars_csv(csv_path)
    metadata_bar_count = input_metadata.get("bar_count")
    if isinstance(metadata_bar_count, bool) or not isinstance(metadata_bar_count, int):
        raise ValueError("bar provenance bar_count must be an integer")
    if metadata_bar_count != len(bars):
        raise ValueError("bar count does not match its provenance metadata")
    utc = timezone.utc
    if first_bar.astimezone(utc) != bars[0].timestamp.astimezone(utc):
        raise ValueError("first bar does not match its provenance metadata")
    if last_bar.astimezone(utc) != bars[-1].timestamp.astimezone(utc):
        raise ValueError("last bar does not match its provenance metadata")
    if (
        bars[0].timestamp.astimezone(utc) < requested_start.astimezone(utc)
        or bars[-1].timestamp.astimezone(utc) > requested_end.astimezone(utc)
    ):
        raise ValueError("bar data falls outside its declared requested range")
    base = Backtester(config).run(bars)
    stress_slippage_bps = max(25.0, float(config.slippage_bps) + 15.0)
    stress = Backtester(
        config,
        slippage_bps=stress_slippage_bps,
        minimum_order_fee=0.01,
    ).run(bars)
    report: dict[str, object] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "paper_only": True,
        "research_warning": (
            "Historical performance is not a promise, forecast, or authorization for live trading. "
            "This report does not enforce the frozen holdout promotion gate."
        ),
        "input": {
            "csv": str(csv_path.resolve()),
            "csv_sha256": csv_sha256,
            "config_sha256": _config_hash(config),
            "config": config.as_dict(),
            "implementation_sha256": _implementation_hash(),
            "symbol": config.symbol,
            "strategy": config.strategy,
            "provenance_path": str(metadata_path.resolve()),
            "provenance": input_metadata,
        },
        "base": base.as_dict(args.include_equity_curve),
        "stress": stress.as_dict(args.include_equity_curve),
        "preliminary_full_sample_diagnostics": {
            "base_positive": base.metrics["total_return_percent"] > 0,
            "stress_positive": stress.metrics["total_return_percent"] > 0,
            "at_least_30_completed_round_trips": stress.metrics[
                "completed_round_trips"
            ]
            >= 30,
            "stress_drawdown_below_configured_limit": stress.metrics[
                "max_drawdown_percent"
            ]
            < config.max_drawdown_fraction * 100,
            "promotion_gate_evaluated": False,
        },
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "kill-switch":
            return _kill_switch(args.config)
        config = _load_config(args.config)
        if args.command == "validate-config":
            _json_print({"valid": True, "paper_only": True, "config": config.as_dict()})
            return 0

        if args.command == "download":
            credentials = AlpacaCredentials.from_environment()
            with AlpacaPaperClient(credentials) as client:
                bars = client.get_daily_bars(
                    config.symbol,
                    start=args.start,
                    end=args.end,
                    feed=config.data_feed,
                )
            output = save_bars_csv(args.output, bars)
            metadata_path = Path(f"{output}.meta.json")
            metadata = {
                "schema_version": 1,
                "source": "alpaca_market_data_api",
                "symbol": config.symbol,
                "feed": config.data_feed,
                "timeframe": "1Day",
                "adjustment": "all",
                "requested_start": args.start.isoformat(),
                "requested_end": args.end.isoformat(),
                "first_bar": bars[0].timestamp.isoformat(),
                "last_bar": bars[-1].timestamp.isoformat(),
                "bar_count": len(bars),
                "csv_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _json_print(
                {
                    "saved": str(output.resolve()),
                    "metadata": str(metadata_path.resolve()),
                    "bars": len(bars),
                    "start": bars[0].timestamp.isoformat(),
                    "end": bars[-1].timestamp.isoformat(),
                }
            )
            return 0

        if args.command == "backtest":
            report = _backtest(args, config)
            _json_print(
                {
                    "input": report["input"],
                    "base_metrics": report["base"]["metrics"],  # type: ignore[index]
                    "stress_metrics": report["stress"]["metrics"],  # type: ignore[index]
                    "preliminary_full_sample_diagnostics": report[
                        "preliminary_full_sample_diagnostics"
                    ],
                    "report": str(Path(args.report).resolve()) if args.report else None,
                }
            )
            return 0

        store = TradingStateStore(config.runtime_directory)
        if args.command == "show-state":
            _json_print(store.load().as_dict())
            return 0

        credentials = AlpacaCredentials.from_environment()
        with AlpacaPaperClient(credentials) as client:
            if args.command == "paper":
                result = PaperTradingEngine(config, client, store).run_once(
                    submit_paper_order=args.submit_paper_order
                )
                _json_print(result)
                return 0
    except (TradingConfigError, BrokerError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2
