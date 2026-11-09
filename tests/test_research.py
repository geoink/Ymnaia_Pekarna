import numpy as np
import pandas as pd
import pytest

from bakery_forecast.metrics import paired_day_bootstrap
from bakery_forecast.research import scaled_metrics, seasonal_scales


def test_scale_preserves_unknown_calendar_days_and_uses_supplied_history_only():
    frame = pd.DataFrame({"date": pd.date_range("2022-01-01", periods=10),
                          "product": "bread", "y": np.arange(10, dtype=float)})
    frame.loc[1, "y"] = np.nan
    scale = seasonal_scales(frame).loc["bread"]
    assert scale.scale_pairs == 2  # (7,0) and (9,2); (8,1) unknown
    assert scale.mae_scale == 7
    assert scale.mse_scale == 49
    frame.loc[9, "y"] = 999  # future relative to the training cutoff
    before_cutoff = seasonal_scales(frame[frame.date < "2022-01-10"]).loc["bread"]
    assert before_cutoff.scale_pairs == 1
    assert before_cutoff.mae_scale == 7
    with pytest.raises(ValueError, match="complete daily calendar"):
        seasonal_scales(frame.drop(index=1))


def test_scaled_metrics_are_macro_and_report_undefined_scales():
    predictions = pd.DataFrame({"product": ["a", "a", "b", "constant"],
                                "y": [10, 10, 100, 0], "model": [12, 8, 108, 1]})
    scales = pd.DataFrame({"product": ["a", "b", "constant"],
                           "mae_scale": [2, 4, 0], "mse_scale": [4, 16, 0]}).set_index("product")
    metrics = scaled_metrics(predictions, "model", scales)
    assert metrics["macro_mase_7"] == pytest.approx(1.5)
    assert metrics["macro_rmsse_7"] == pytest.approx(1.5)
    assert metrics["scaled_products"] == 2


def test_bootstrap_keeps_pairs_and_supports_calendar_blocks():
    frame = pd.DataFrame({"date": pd.to_datetime(["2022-01-01", "2022-01-03"]),
                          "y": [10, 10], "perfect": [10, 10], "reference": [12, 12]})
    result = paired_day_bootstrap(frame, "perfect", "reference", repeats=30)
    assert result["low_pp"] == result["high_pp"] == -20
    assert result["block_days"] == 3  # caps at calendar length, not observed count
    single = paired_day_bootstrap(frame, "perfect", "reference", repeats=30, block_days=1)
    assert single["low_pp"] == single["high_pp"] == -20
    assert single["block_days"] == 1


@pytest.mark.parametrize("block", [0, -1, 1.5, True])
def test_bootstrap_rejects_invalid_block(block):
    with pytest.raises(ValueError, match="block_days"):
        paired_day_bootstrap(pd.DataFrame(), "a", "b", block_days=block)
