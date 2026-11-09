"""All historical features for day t use observations strictly before t."""

import numpy as np
import pandas as pd

from .config import FEATURES


def make_features(panel: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for _, part in panel.groupby("product", sort=True):
        part = part.sort_values("date").copy()
        # A daily calendar is required, so shift(7) means seven calendar days.
        if not part.date.diff().dropna().eq(pd.Timedelta(days=1)).all():
            raise ValueError("Feature input must have one row per calendar day and product")
        y = part.y
        past = y.shift(1)
        for lag in (1, 7, 14, 28):
            part[f"lag_{lag}"] = y.shift(lag)
        part["mean_7"] = past.rolling(7, min_periods=1).mean()
        part["mean_28"] = past.rolling(28, min_periods=1).mean()
        part["std_28"] = past.rolling(28, min_periods=2).std()
        part["observed_days_28"] = past.rolling(28, min_periods=1).count()
        weekdays = pd.concat([y.shift(lag) for lag in (7, 14, 21, 28)], axis=1)
        part["weekday_mean_4"] = weekdays.mean(axis=1)
        part["weekday_median_4"] = weekdays.median(axis=1)
        part["past_mean"] = past.expanding(min_periods=1).mean()
        pieces.append(part)
    frame = pd.concat(pieces, ignore_index=True)
    frame["dow"] = frame.date.dt.day_of_week
    frame["month"] = frame.date.dt.month
    frame["weekend"] = frame.dow.ge(5).astype(int)
    angle = 2 * np.pi * frame.date.dt.day_of_year / 365.25
    frame["annual_sin"], frame["annual_cos"] = np.sin(angle), np.cos(angle)
    frame["trend"] = (frame.date - pd.Timestamp("2021-01-01")).dt.days
    frame["product"] = pd.Categorical(frame["product"], categories=sorted(panel["product"].unique()))
    return frame.sort_values(["date", "product"]).reset_index(drop=True)


def baseline(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in ("lag_7", "weekday_mean_4"):
        raise ValueError(f"Unknown baseline: {name}")
    # Fallbacks use only previously observed days and are identical across splits.
    values = frame[name].fillna(frame["mean_28"]).fillna(frame["past_mean"])
    if values.isna().any():
        raise ValueError("Not enough observed history for prediction")
    return values.clip(lower=0).to_numpy(dtype=float)


def model_input(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[FEATURES]
