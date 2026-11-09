"""Expanding-window selection, frozen holdout, and validation-only policy tuning."""

import importlib.metadata
import platform
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import (BASELINES, CANDIDATES, COST_RATIOS, ML_MODELS, PRODUCTS,
                     SAFETY_MULTIPLIERS, SEED, TEST_END, TEST_START, VALIDATION_FOLDS,
                     WARMUP_DAYS)
from .data import daily_panel, read_transactions, write_json
from .features import make_features
from .metrics import inventory_loss, paired_day_bootstrap, regression_metrics
from .model import fit_models, predict_candidates


def price_map(transactions, cutoff):
    history = transactions[(transactions.date < pd.Timestamp(cutoff)) & transactions.price.gt(0)]
    prices = history.groupby("product").price.median()
    if not set(PRODUCTS).issubset(prices.index):
        raise ValueError("Missing positive historical prices for the selected products")
    return prices


def evaluate_window(frame, transactions, start, end):
    training = frame[(frame.date < start) & frame.y.notna()]
    evaluation = frame[(frame.date >= start) & (frame.date < end) & frame.y.notna()]
    if training.empty or evaluation.empty:
        raise ValueError(f"Empty training or evaluation window: {start} .. {end}")
    models = fit_models(training)
    output = evaluation[["date", "product", "y"]].copy()
    output["price_eur_assumption"] = output['product'].astype(str).map(price_map(transactions, start)).astype(float)
    for name, values in predict_candidates(evaluation, models).items():
        output[name] = values
    output["fold"] = start
    return output


def metric_table(predictions, names=CANDIDATES):
    return pd.DataFrame([{"model": name, **regression_metrics(predictions.y, predictions[name])} for name in names])


def run_experiment(raw_path: Path, root: Path) -> dict:
    root = Path(root)
    for directory in ("data/processed", "reports", "reports/figures", "models"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    transactions, audit = read_transactions(raw_path)
    if transactions.date.max() >= pd.Timestamp(TEST_END):
        raise ValueError("This evaluation protocol ends on 2022-09-30. Define a new protocol for newer data.")
    panel = daily_panel(transactions)
    frame = make_features(panel)
    frame = frame[frame.date >= frame.date.min() + pd.Timedelta(days=WARMUP_DAYS)].copy()
    audit["selected_products"] = list(PRODUCTS)
    audit["negative_product_day_totals_clipped"] = int(panel.net_quantity.lt(0).sum())
    audit["product_days_assumed_zero"] = int(panel.product_absence_assumed_zero.sum())
    audit["unknown_product_days"] = int(panel.y.isna().sum())
    audit["selected_net_sales_units"] = float(panel.y.sum())
    write_json(root / "reports/data_audit.json", audit)
    panel.to_csv(root / "data/processed/daily_sales.csv", index=False)

    validations = []
    for start, end in VALIDATION_FOLDS:
        print(f"Validation {start} .. {end}", flush=True)
        validations.append(evaluate_window(frame, transactions, start, end))
    validation = pd.concat(validations, ignore_index=True)
    val_metrics = metric_table(validation)
    scores = val_metrics.set_index("model").wape_pct
    selected = min(CANDIDATES, key=lambda name: scores[name])
    best_baseline = min(BASELINES, key=lambda name: scores[name])
    best_ml = min(ML_MODELS, key=lambda name: scores[name])
    # The choice and all policy multipliers are fixed before accessing test labels.
    policies = []
    for ratio in COST_RATIOS:
        for name in CANDIDATES:
            losses = [inventory_loss(validation.y, validation[name], validation.price_eur_assumption,
                                     ratio, multiplier)["loss_eur"] for multiplier in SAFETY_MULTIPLIERS]
            chosen_multiplier = SAFETY_MULTIPLIERS[int(np.argmin(losses))]
            policies.append({"model": name, "cost_ratio": ratio, "multiplier": chosen_multiplier,
                             "validation_loss_eur": min(losses)})
    selection = {"selected_model": selected, "best_baseline": best_baseline, "best_ml": best_ml,
                 "criterion": "Pooled WAPE across June and July expanding-window validation",
                 "candidates": list(CANDIDATES), "policies": policies}
    write_json(root / "reports/selection.json", selection)
    print(f"Selected on validation: {selected}. Evaluating untouched test period.", flush=True)
    test = evaluate_window(frame, transactions, TEST_START, TEST_END)
    test_metrics = metric_table(test)
    economic_rows = []
    for policy in policies:
        values = inventory_loss(test.y, test[policy["model"]], test.price_eur_assumption,
                                policy["cost_ratio"], policy["multiplier"])
        economic_rows.append({**policy, **values})
    economics = pd.DataFrame(economic_rows)
    per_product = []
    for product, part in test.groupby("product", observed=True):
        for name in CANDIDATES:
            per_product.append({"product": str(product), "model": name,
                                **regression_metrics(part.y, part[name])})
    monthly = []
    for month, part in test.groupby(test.date.dt.to_period("M")):
        for name in CANDIDATES:
            monthly.append({"month": str(month), "model": name, **regression_metrics(part.y, part[name])})
    folds = []
    for fold, part in validation.groupby("fold"):
        for name in CANDIDATES:
            folds.append({"fold": str(fold), "model": name, **regression_metrics(part.y, part[name])})
    for filename, table in (
        ("validation_metrics", val_metrics), ("test_metrics", test_metrics),
        ("metrics_by_product", pd.DataFrame(per_product)), ("metrics_by_month", pd.DataFrame(monthly)),
        ("validation_by_fold", pd.DataFrame(folds)), ("economic_scenarios", economics),
        ("predictions_validation", validation), ("predictions_test", test),
    ):
        table.to_csv(root / f"reports/{filename}.csv", index=False)
    comparison = paired_day_bootstrap(test, best_ml, best_baseline, seed=SEED)
    test_scores = test_metrics.set_index("model")
    reference_wape = float(test_scores.loc[best_baseline, "wape_pct"])
    ml_wape = float(test_scores.loc[best_ml, "wape_pct"])
    summary = {
        **selection, "seed": SEED, "data_sha256": audit["sha256"],
        "test_start": TEST_START, "test_end_exclusive": TEST_END,
        "test_observed_days": int(test.date.nunique()), "test_rows": len(test),
        "validation_rows": len(validation), "test_metrics": test_metrics.to_dict(orient="records"),
        "validation_metrics": val_metrics.to_dict(orient="records"),
        "ml_relative_wape_reduction_pct": 100 * (reference_wape - ml_wape) / reference_wape,
        "ml_minus_baseline_wape_ci": comparison,
        "python": platform.python_version(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ["numpy", "pandas", "scikit-learn", "matplotlib", "joblib"]},
    }
    write_json(root / "reports/summary.json", summary)
    # Deployment refit is separate from the frozen test results above.
    deploy_models = fit_models(frame[frame.y.notna()]) if selected in ML_MODELS else {}
    bundle = {"selected_model": selected, "models": deploy_models, "products": list(PRODUCTS),
              "trained_through": str(transactions.date.max().date()), "data_sha256": audit["sha256"],
              "scope": "next calendar day, assuming the shop is open"}
    joblib.dump(bundle, root / "models/forecast.joblib")
    from .reporting import create_figures, write_results
    create_figures(panel, validation, test, summary, economics, root)
    write_results(summary, audit, economics, root)
    return summary


def predict_next_day(raw_path: Path, bundle_path: Path) -> pd.DataFrame:
    # Load only artifacts produced locally: joblib/pickle is not safe for untrusted files.
    bundle = joblib.load(bundle_path)
    transactions, _ = read_transactions(raw_path)
    if transactions.date.max() < pd.Timestamp(bundle["trained_through"]):
        raise ValueError("History ends before model training: use a matching artifact to avoid look-ahead")
    if (transactions.date.max() - transactions.date.min()).days < WARMUP_DAYS:
        raise ValueError("At least 35 calendar days of history are required")
    target_date = transactions.date.max() + pd.Timedelta(days=1)
    frame = make_features(daily_panel(transactions, bundle["products"], end_date=target_date))
    future = frame[frame.date.eq(target_date)]
    predictions = predict_candidates(future, bundle["models"])[bundle["selected_model"]]
    output = future[["date", "product"]].copy()
    output["forecast_units"] = np.round(predictions, 2)
    output["rounded_units"] = np.floor(predictions + 0.5).astype(int)
    output["model"] = bundle["selected_model"]
    return output
