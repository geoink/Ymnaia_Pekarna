"""Forecast metrics and a clearly hypothetical one-day inventory loss."""

import numpy as np
import pandas as pd


def regression_metrics(actual, predicted) -> dict:
    y, pred = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if y.shape != pred.shape or y.size == 0 or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError("Metrics require equally sized, finite, nonempty arrays")
    error = pred - y
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "wape_pct": float(100 * np.abs(error).sum() / y.sum()) if y.sum() > 0 else None,
        "bias_units": float(error.mean()), "n": int(y.size),
    }


def inventory_loss(actual, forecast, price, cost_ratio: float, multiplier: float = 1.0) -> dict:
    """Assume sales equal demand; no salvage, carryover, capacity limit or substitution."""
    if not 0 < cost_ratio < 1 or multiplier <= 0:
        raise ValueError("Require 0 < cost_ratio < 1 and positive multiplier")
    y, f, p = np.broadcast_arrays(np.asarray(actual, float), np.asarray(forecast, float), np.asarray(price, float))
    if not all(np.isfinite(a).all() for a in (y, f, p)) or (y < 0).any() or (p <= 0).any():
        raise ValueError("Require finite arrays, nonnegative sales, and positive prices")
    plan = np.floor(np.maximum(0, f) * multiplier + 0.5)
    surplus = np.maximum(plan - y, 0)
    shortage = np.maximum(y - plan, 0)
    waste_cost = float(np.sum(surplus * p * cost_ratio))
    missed_margin = float(np.sum(shortage * p * (1 - cost_ratio)))
    return {"loss_eur": waste_cost + missed_margin, "surplus_units": float(surplus.sum()),
            "shortage_units": float(shortage.sum()), "waste_cost_eur": waste_cost,
            "missed_margin_eur": missed_margin}


def paired_day_bootstrap(predictions, candidate: str, reference: str, repeats=2000, seed=42, block_days=7):
    """Paired moving-block bootstrap of difference in WAPE percentage points."""
    if type(block_days) is not int or block_days < 1:
        raise ValueError("block_days must be a positive integer")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if predictions.empty:
        raise ValueError("Bootstrap requires observations")
    frame = predictions.copy()
    frame["candidate_error"] = abs(frame[candidate] - frame.y)
    frame["reference_error"] = abs(frame[reference] - frame.y)
    grouped = frame.groupby("date")[["y", "candidate_error", "reference_error"]].sum()
    # Keep missing calendar days as zero-weight days, not zero-demand observations.
    grouped = grouped.reindex(pd.date_range(grouped.index.min(), grouped.index.max()), fill_value=0)
    values = grouped.to_numpy()
    length, block = len(values), min(block_days, len(values))
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(repeats):
        starts = rng.integers(0, length - block + 1, size=int(np.ceil(length / block)))
        idx = np.concatenate([np.arange(start, start + block) for start in starts])[:length]
        total = values[idx].sum(axis=0)
        if total[0] > 0:
            differences.append(100 * (total[1] - total[2]) / total[0])
    if not differences:
        raise ValueError("Bootstrap requires positive total sales")
    low, high = np.percentile(differences, [2.5, 97.5])
    return {"low_pp": float(low), "high_pp": float(high), "repeats": repeats, "block_days": block,
            "interpretation": "candidate WAPE minus reference WAPE; negative favors candidate; approximate interval"}
