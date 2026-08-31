from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rareiq.trading.config import TradingConfig
from rareiq.trading.models import Bar, ModelSignal


MIN_FEATURE_BARS = 100


@dataclass(slots=True)
class _FittedModel:
    weights: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    trained_at_index: int
    training_samples: int


def _feature_vector(closes: np.ndarray, index: int) -> np.ndarray:
    if index < MIN_FEATURE_BARS:
        raise ValueError("insufficient history for features")
    returns = np.diff(np.log(closes[index - 20 : index + 1]))
    sma20 = float(np.mean(closes[index - 19 : index + 1]))
    sma100 = float(np.mean(closes[index - 99 : index + 1]))
    high60 = float(np.max(closes[index - 59 : index + 1]))
    return np.asarray(
        [
            np.log(closes[index] / closes[index - 1]),
            np.log(closes[index] / closes[index - 5]),
            np.log(closes[index] / closes[index - 20]),
            closes[index] / sma20 - 1.0,
            sma20 / sma100 - 1.0,
            float(np.std(returns, ddof=1) * np.sqrt(252.0)),
            closes[index] / high60 - 1.0,
        ],
        dtype=np.float64,
    )


class WalkForwardLogisticStrategy:
    """Small, inspectable direction model with strict look-ahead prevention.

    Each label is known before the prediction bar, model fitting uses a bounded
    trailing window, and executions are left to the next bar by the backtester.
    This is a research baseline, not evidence that a profitable edge exists.
    """

    def __init__(self, config: TradingConfig) -> None:
        self.config = config
        self._fitted: _FittedModel | None = None

    def _training_set(
        self, closes: np.ndarray, as_of_index: int
    ) -> tuple[np.ndarray, np.ndarray]:
        horizon = self.config.prediction_horizon_bars
        last_labeled_index = as_of_index - horizon
        first_index = max(MIN_FEATURE_BARS, last_labeled_index - self.config.training_window_bars + 1)
        if last_labeled_index < first_index:
            return np.empty((0, 7)), np.empty((0,))
        indices = range(first_index, last_labeled_index + 1)
        features = np.vstack([_feature_vector(closes, index) for index in indices])
        hurdle = self.config.return_hurdle_bps / 10_000.0
        labels = np.asarray(
            [
                float(np.log(closes[index + horizon] / closes[index]) > hurdle)
                for index in indices
            ],
            dtype=np.float64,
        )
        return features, labels

    def _fit(self, closes: np.ndarray, as_of_index: int) -> _FittedModel | None:
        features, labels = self._training_set(closes, as_of_index)
        if len(labels) < self.config.minimum_training_samples:
            return None
        means = np.mean(features, axis=0)
        scales = np.std(features, axis=0)
        scales = np.where(scales < 1e-9, 1.0, scales)
        standardized = (features - means) / scales
        design = np.column_stack((np.ones(len(standardized)), standardized))

        positive_rate = float(np.clip(np.mean(labels), 1e-4, 1 - 1e-4))
        weights = np.zeros(design.shape[1], dtype=np.float64)
        weights[0] = np.log(positive_rate / (1.0 - positive_rate))
        recency_weights = np.linspace(0.6, 1.0, len(labels), dtype=np.float64)
        normalization = float(np.sum(recency_weights))

        for _ in range(300):
            logits = np.clip(design @ weights, -30.0, 30.0)
            probabilities = 1.0 / (1.0 + np.exp(-logits))
            error = (probabilities - labels) * recency_weights
            gradient = design.T @ error / normalization
            gradient[1:] += 0.02 * weights[1:]
            weights -= 0.05 * gradient

        return _FittedModel(
            weights=weights,
            means=means,
            scales=scales,
            trained_at_index=as_of_index,
            training_samples=len(labels),
        )

    def signal(self, bars: list[Bar], current_fraction: float = 0.0) -> ModelSignal:
        if not bars:
            raise ValueError("strategy requires at least one bar")
        as_of_index = len(bars) - 1
        closes = np.asarray([bar.close for bar in bars], dtype=np.float64)
        fitted = self._fitted
        needs_fit = (
            fitted is None
            or as_of_index < fitted.trained_at_index
            or as_of_index - fitted.trained_at_index >= self.config.retrain_every_bars
        )
        if needs_fit:
            fitted = self._fit(closes, as_of_index)
            self._fitted = fitted
        if fitted is None or as_of_index < MIN_FEATURE_BARS:
            return ModelSignal(
                as_of=bars[-1].timestamp,
                probability_up=0.5,
                target_fraction=0.0,
                action="wait",
                training_samples=0,
                reasons=("insufficient_walk_forward_history",),
            )

        features = _feature_vector(closes, as_of_index)
        standardized = (features - fitted.means) / fitted.scales
        design = np.concatenate(([1.0], standardized))
        logit = float(np.clip(design @ fitted.weights, -30.0, 30.0))
        probability = 1.0 / (1.0 + np.exp(-logit))
        trend_positive = bool(features[4] > 0)

        if probability >= self.config.entry_probability and trend_positive:
            target = self.config.max_position_fraction
            action = "enter_or_add"
        elif probability <= self.config.exit_probability or not trend_positive:
            target = 0.0
            action = "exit_or_stay_out"
        else:
            target = min(max(current_fraction, 0.0), self.config.max_position_fraction)
            action = "hold"

        return ModelSignal(
            as_of=bars[-1].timestamp,
            probability_up=probability,
            target_fraction=target,
            action=action,
            training_samples=fitted.training_samples,
            reasons=(
                f"sma20_above_sma100={str(trend_positive).lower()}",
                f"entry_threshold={self.config.entry_probability:.2f}",
                f"exit_threshold={self.config.exit_probability:.2f}",
            ),
        )


class SmaRegimeStrategy:
    """Frozen, deterministic safety baseline for paper execution."""

    window = 200

    def __init__(self, config: TradingConfig) -> None:
        self.config = config

    def signal(self, bars: list[Bar], current_fraction: float = 0.0) -> ModelSignal:
        if not bars:
            raise ValueError("strategy requires at least one bar")
        if len(bars) < self.window:
            return ModelSignal(
                as_of=bars[-1].timestamp,
                probability_up=0.5,
                target_fraction=0.0,
                action="wait",
                training_samples=0,
                reasons=("insufficient_200_day_history",),
            )
        closes = np.asarray([bar.close for bar in bars[-self.window :]], dtype=np.float64)
        average = float(np.mean(closes))
        above = bool(bars[-1].close > average)
        return ModelSignal(
            as_of=bars[-1].timestamp,
            probability_up=1.0 if above else 0.0,
            target_fraction=self.config.max_position_fraction if above else 0.0,
            action="enter_or_add" if above else "exit_or_stay_out",
            training_samples=self.window,
            reasons=(
                f"close={bars[-1].close:.4f}",
                f"sma200={average:.4f}",
                "frozen_deterministic_baseline",
            ),
        )


def build_strategy(
    config: TradingConfig,
) -> SmaRegimeStrategy | WalkForwardLogisticStrategy:
    if config.strategy == "sma_regime":
        return SmaRegimeStrategy(config)
    return WalkForwardLogisticStrategy(config)
