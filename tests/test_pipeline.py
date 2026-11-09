
import joblib
import numpy as np
import pandas as pd
import pytest

from bakery_forecast.config import FEATURES
from bakery_forecast.data import daily_panel, download_data, read_transactions
from bakery_forecast.experiment import predict_next_day
from bakery_forecast.features import baseline, make_features
from bakery_forecast.metrics import inventory_loss, regression_metrics
from bakery_forecast.model import fit_models, predict_candidates


def transactions(days=80):
    dates = pd.date_range("2022-01-01", periods=days)
    return pd.DataFrame([
        {"date": day, "product": product, "quantity": float(10 + day.day_of_week + offset), "price": 2.0}
        for day in dates for product, offset in [("BREAD", 0), ("BUN", 3)]
    ])


def test_calendar_gap_is_unknown_and_missing_sku_is_zero():
    tx = transactions(4)
    tx = tx[~tx.date.eq("2022-01-02")]
    tx = tx[~(tx.date.eq("2022-01-03") & tx['product'].eq("BUN"))]
    panel = daily_panel(tx, ["BREAD", "BUN"])
    assert panel.loc[panel.date.eq("2022-01-02"), "y"].isna().all()
    assert panel.loc[panel.date.eq("2022-01-03") & panel['product'].eq("BUN"), "y"].item() == 0


def test_future_and_current_targets_do_not_change_current_features():
    tx = transactions()
    original = daily_panel(tx, ["BREAD", "BUN"])
    changed = original.copy()
    changed.loc[changed.date >= "2022-02-15", "y"] = 100_000
    before = make_features(original)
    after = make_features(changed)
    pd.testing.assert_frame_equal(
        before.loc[before.date <= "2022-02-15", FEATURES],
        after.loc[after.date <= "2022-02-15", FEATURES],
    )


def test_lag_seven_uses_calendar_days_including_unknown_days():
    tx = transactions(30)
    tx = tx[~tx.date.eq("2022-01-02")]
    frame = make_features(daily_panel(tx, ["BREAD", "BUN"]))
    assert frame.loc[frame.date.eq("2022-01-09"), "lag_7"].isna().all()
    expected = tx.loc[tx.date.eq("2022-01-03"), "quantity"].to_numpy()
    np.testing.assert_allclose(frame.loc[frame.date.eq("2022-01-10"), "lag_7"], expected)


def test_weekday_baseline_uses_previous_four_matching_weekdays():
    tx = transactions(36)
    tx.loc[tx['product'].eq("BREAD"), "quantity"] = np.arange(36)
    frame = make_features(daily_panel(tx, ["BREAD", "BUN"]))
    row = frame[frame.date.eq("2022-02-05") & frame['product'].eq("BREAD")]
    assert baseline(row, "weekday_mean_4").item() == np.mean([28, 21, 14, 7])


def test_returns_are_netted_and_identical_rows_retained(tmp_path):
    path = tmp_path / "source.csv"
    pd.DataFrame({"date": ["2022-01-01"] * 3, "time": ["12:00"] * 3,
                  "ticket_number": [1, 1, 2], "article": ["BREAD"] * 3,
                  "Quantity": [2, 2, -1], "unit_price": ["1,50 €"] * 3}).to_csv(path, index=False)
    tx, audit = read_transactions(path)
    assert len(tx) == 3
    assert audit["negative_quantity_rows_retained"] == 1
    assert audit["repeated_content_rows_retained"] == 1
    assert daily_panel(tx, ["BREAD"]).y.item() == 3
    assert tx.price.eq(1.5).all()


def test_negative_daily_total_clipped_not_negative_target():
    tx = transactions(3)
    tx.loc[tx.date.eq("2022-01-02"), "quantity"] = -2
    panel = daily_panel(tx, ["BREAD", "BUN"])
    assert panel.loc[panel.date.eq("2022-01-02"), "y"].eq(0).all()
    assert panel.loc[panel.date.eq("2022-01-02"), "net_quantity"].eq(-2).all()


def test_metrics_and_zero_denominator():
    metrics = regression_metrics([10, 20], [12, 16])
    assert metrics["mae"] == 3
    assert metrics["wape_pct"] == 20
    assert regression_metrics([0, 0], [1, 2])["wape_pct"] is None
    with pytest.raises(ValueError):
        regression_metrics([1], [np.nan])


def test_inventory_costs_match_manual_calculation():
    # Price 2, cost 1.2; two excess units cost 2.4, two missing units lose 1.6 margin.
    result = inventory_loss([10, 10], [12, 8], [2, 2], 0.6)
    assert result["loss_eur"] == pytest.approx(4.0)
    assert result["surplus_units"] == 2
    assert result["shortage_units"] == 2
    with pytest.raises(ValueError):
        inventory_loss([1], [1], [2], 1.0)


def test_modified_download_is_rejected_without_network(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("changed")
    with pytest.raises(ValueError, match="differs"):
        download_data(path)


def test_fit_save_and_future_inference(tmp_path):
    tx = transactions()
    frame = make_features(daily_panel(tx, ["BREAD", "BUN"]))
    frame = frame[frame.date >= "2022-02-05"]
    models = fit_models(frame)
    predictions = predict_candidates(frame, models)
    assert set(predictions) == {"lag_7", "weekday_mean_4", "hgb_absolute", "hgb_poisson", "blend_absolute"}
    assert all(np.isfinite(values).all() and (values >= 0).all() for values in predictions.values())
    raw = tx.rename(columns={"product": "article", "quantity": "Quantity", "price": "unit_price"})
    raw["time"], raw["ticket_number"] = "12:00", range(len(raw))
    data_path = tmp_path / "source.csv"
    raw.to_csv(data_path, index=False)
    model_path = tmp_path / "model.joblib"
    bundle = {"models": models, "products": ["BREAD", "BUN"], "selected_model": "blend_absolute",
              "trained_through": str(tx.date.max().date())}
    joblib.dump(bundle, model_path)
    forecast = predict_next_day(data_path, model_path)
    assert len(forecast) == 2
    assert forecast.date.eq(tx.date.max() + pd.Timedelta(days=1)).all()
    assert forecast.forecast_units.ge(0).all()
    bundle["trained_through"] = "2023-01-01"
    joblib.dump(bundle, model_path)
    with pytest.raises(ValueError, match="before model training"):
        predict_next_day(data_path, model_path)


def test_non_daily_feature_input_is_rejected():
    panel = daily_panel(transactions(), ["BREAD", "BUN"])
    panel = panel[~panel.date.eq("2022-01-02")]
    with pytest.raises(ValueError, match="calendar day"):
        make_features(panel)


