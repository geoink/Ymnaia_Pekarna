"""Read user sales and evaluate a fresh daily model without changing coursework reports."""

from datetime import date, datetime
import csv
import io
from pathlib import Path
import re
import zipfile

import numpy as np
import pandas as pd

from .config import WARMUP_DAYS
from .data import daily_panel
from .features import make_features
from .metrics import regression_metrics
from .model import fit_models, predict_candidates


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000
MAX_PRODUCTS = 100
MAX_CALENDAR_DAYS = 5 * 366
MIN_CALENDAR_DAYS = 84
CHECK_DAYS = 14
ALIASES = {
    "date": {"date", "дата", "дата продажи", "день"},
    "product": {"product", "article", "товар", "название", "наименование", "позиция", "sku"},
    "quantity": {"quantity", "sales", "units", "количество", "продажи", "продано", "шт"},
}


def read_upload(content: bytes, filename: str) -> pd.DataFrame:
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Выберите непустой файл размером до 8 МБ.")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".xlsx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if (
                    len(archive.infolist()) > 2000
                    or sum(x.file_size for x in archive.infolist()) > 80 * 1024 * 1024
                ):
                    raise ValueError(
                        "Слишком большая книга Excel. Сохраните лист продаж отдельно в CSV."
                    )
            table = pd.read_excel(io.BytesIO(content), engine="openpyxl", nrows=MAX_ROWS + 1)
        elif suffix == ".csv":
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1251")
            try:
                delimiter = csv.Sniffer().sniff(text[:16000], delimiters=",;\t").delimiter
            except csv.Error:
                delimiter = ";" if ";" in text.splitlines()[0] else ","
            table = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, nrows=MAX_ROWS + 1)
        else:
            raise ValueError(
                "Поддерживаются CSV и Excel .xlsx. Сохраните файл в одном из этих форматов."
            )
    except ImportError as exc:
        raise ValueError(
            "Для Excel нужна библиотека openpyxl. Запустите приложение через файл запуска или загрузите CSV."
        ) from exc
    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        UnicodeError,
        zipfile.BadZipFile,
    ) as exc:
        raise ValueError(
            "Не удалось прочитать таблицу. Проверьте формат файла и строку заголовков."
        ) from exc
    if table.empty or len(table) > MAX_ROWS or len(table.columns) > 60:
        raise ValueError("Нужна таблица от 1 до 100 000 строк и до 60 столбцов.")
    columns = [str(c).strip() for c in table.columns]
    if len(set(columns)) != len(columns) or any(not c for c in columns):
        raise ValueError("Столбцы должны иметь разные непустые названия.")
    table.columns = columns
    return table


def suggest_columns(table: pd.DataFrame) -> dict:
    return {
        key: next((c for c in table.columns if c.lower().strip() in aliases), None)
        for key, aliases in ALIASES.items()
    }


def parse_dates(values: pd.Series) -> pd.Series:
    def one(value):
        if isinstance(value, (pd.Timestamp, datetime, date)):
            timestamp = pd.Timestamp(value)
            return timestamp.normalize() if timestamp.tzinfo is None else pd.NaT
        if not isinstance(value, str):
            return pd.NaT
        text = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
            return pd.to_datetime(text, format="%d.%m.%Y", errors="coerce")
        return pd.NaT

    return pd.to_datetime(values.map(one), errors="coerce")


def normalize_sales(table: pd.DataFrame, columns: dict) -> tuple[pd.DataFrame, dict]:
    if set(columns) != {"date", "product", "quantity"} or not all(
        isinstance(v, str) for v in columns.values()
    ):
        raise ValueError("Выберите столбцы даты, товара и количества.")
    if len(set(columns.values())) != 3 or not set(columns.values()).issubset(table.columns):
        raise ValueError("Дата, товар и количество должны находиться в трёх разных столбцах.")
    raw = table[[columns[k] for k in ("date", "product", "quantity")]].copy()
    raw.columns = ["date", "product", "quantity"]
    dates = parse_dates(raw.date)
    products = raw["product"].astype("string").str.strip()
    numbers = (
        raw.quantity.astype("string")
        .str.replace(r"[\s\u00a0]", "", regex=True)
        .str.replace(",", ".", regex=False)
    )
    quantity = pd.to_numeric(numbers, errors="coerce").astype(float)
    invalid = (
        dates.isna()
        | products.isna()
        | products.eq("")
        | products.str.len().gt(120)
        | ~np.isfinite(quantity)
        | quantity.abs().gt(10_000_000)
    )
    if invalid.any():
        rows = ", ".join(str(int(i) + 2) for i in np.flatnonzero(invalid.to_numpy())[:8])
        raise ValueError(
            f"Проверьте строки {rows}. Дата нужна в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ, товар — текст, количество — число."
        )
    sales = pd.DataFrame({"date": dates, "product": products.astype(str), "quantity": quantity})
    if sales["product"].nunique() > MAX_PRODUCTS:
        raise ValueError(
            f"В одном расчёте поддерживается до {MAX_PRODUCTS} товаров. Сократите ассортимент в файле."
        )
    span = (sales.date.max() - sales.date.min()).days + 1
    if span > MAX_CALENDAR_DAYS or sales.date.min().year < 1900 or sales.date.max().year > 2100:
        raise ValueError(
            "Проверьте даты. Поддерживается история до пяти лет в диапазоне 1900–2100."
        )
    daily = sales.groupby(["date", "product"], as_index=False).quantity.sum()
    audit = {
        "rows": len(sales),
        "products": sales["product"].nunique(),
        "first_date": str(sales.date.min().date()),
        "last_date": str(sales.date.max().date()),
        "calendar_days": span,
        "observed_days": sales.date.nunique(),
        "missing_days": span - sales.date.nunique(),
        "combined_rows": len(sales) - len(daily),
        "negative_rows": int(sales.quantity.lt(0).sum()),
        "negative_totals": int(daily.quantity.lt(0).sum()),
    }
    return daily, audit


def product_summary(sales: pd.DataFrame) -> list[dict]:
    result = []
    for product, part in sales.groupby("product", sort=True):
        result.append(
            {
                "name": product,
                "days": int(part.date.nunique()),
                "units": float(part.quantity.clip(lower=0).sum()),
                "first_date": str(part.date.min().date()),
                "last_date": str(part.date.max().date()),
            }
        )
    return result


def prepare_features(sales: pd.DataFrame, products: list[str], missing: str):
    if (
        not isinstance(products, list)
        or not products
        or not all(isinstance(p, str) for p in products)
    ):
        raise ValueError("Выберите хотя бы один товар.")
    if len(products) != len(set(products)) or not set(products).issubset(sales["product"]):
        raise ValueError("Выбранный ассортимент не совпадает с товарами в файле.")
    if missing not in {"unknown", "zero"}:
        raise ValueError("Выберите правило обработки отсутствующих товаров.")
    first, last = sales.date.min(), sales.date.max()
    if (last - first).days + 1 < MIN_CALENDAR_DAYS:
        raise ValueError(
            "Для обучения и проверки нужно хотя бы 84 календарных дня истории. Можно испытать приложение на демонстрационном файле."
        )
    target = last + pd.Timedelta(days=1)
    panel = daily_panel(sales, products, end_date=target)
    if missing == "unknown":
        panel.loc[panel.product_absence_assumed_zero, "y"] = np.nan
    first_by_product = sales.groupby("product").date.min()
    # Before a product's first observation its availability is unknown, even in zero mode.
    panel.loc[panel.date < panel["product"].map(first_by_product), "y"] = np.nan
    features = make_features(panel)
    features = features[features.date >= first + pd.Timedelta(days=WARMUP_DAYS)].copy()
    cutoff = last - pd.Timedelta(days=CHECK_DAYS - 1)
    training = features[(features.date < cutoff) & features.y.notna()].copy()
    check = features[
        (features.date >= cutoff) & (features.date <= last) & features.y.notna()
    ].copy()
    for name, frame, minimum in [("обучения", training, 28), ("проверки", check, 7)]:
        counts = frame.groupby("product", observed=True).size()
        short = [p for p in products if counts.get(p, 0) < minimum]
        if short:
            raise ValueError(
                f"Недостаточно наблюдений для {name} у товаров {', '.join(short[:5])}. Нужно минимум {minimum} известных дней на каждый товар в этой части истории. Добавьте данные или исключите эти товары."
            )
    return features, training, check, target, cutoff


def run_playground(sales: pd.DataFrame, products: list[str], missing="unknown") -> dict:
    features, training, check, target, cutoff = prepare_features(sales, products, missing)
    models = fit_models(training, include_poisson=False)
    predictions = predict_candidates(check, models)
    check = check[["date", "product", "y"]].copy()
    for name in ("hgb_absolute", "lag_7", "weekday_mean_4"):
        check[name] = predictions[name]
    metrics = {
        name: regression_metrics(check.y, check[name])
        for name in ("hgb_absolute", "lag_7", "weekday_mean_4")
    }
    product_metrics = []
    for product, part in check.groupby("product", observed=True):
        product_metrics.append(
            {
                "product": str(product),
                "ml": regression_metrics(part.y, part.hgb_absolute),
                "baseline": regression_metrics(part.y, part.lag_7),
            }
        )

    final_training = features[features.y.notna() & (features.date < target)]
    final_models = fit_models(final_training, include_poisson=False)
    future = features[features.date.eq(target)].copy()
    future_predictions = predict_candidates(future, final_models)
    forecast = []
    for index, product in enumerate(future["product"]):
        value = float(future_predictions["hgb_absolute"][index])
        forecast.append(
            {
                "product": str(product),
                "forecast": round(value, 2),
                "rounded": int(np.floor(value + 0.5)),
                "lag_7": round(float(future_predictions["lag_7"][index]), 2),
                "weekday_mean_4": round(float(future_predictions["weekday_mean_4"][index]), 2),
            }
        )

    history = []
    for product, part in features[
        features.date.between(target - pd.Timedelta(days=56), target - pd.Timedelta(days=1))
    ].groupby("product", observed=True):
        checked = check[check["product"].eq(product)].set_index("date")
        for row in part.itertuples():
            history.append(
                {
                    "date": str(row.date.date()),
                    "product": str(product),
                    "actual": float(row.y) if pd.notna(row.y) else None,
                    "predicted": float(checked.loc[row.date, "hgb_absolute"])
                    if row.date in checked.index
                    else None,
                }
            )
    return {
        "target_date": str(target.date()),
        "last_date": str((target - pd.Timedelta(days=1)).date()),
        "check_start": str(cutoff.date()),
        "check_end": str((target - pd.Timedelta(days=1)).date()),
        "training_rows": len(training),
        "check_rows": len(check),
        "metrics": metrics,
        "products": product_metrics,
        "forecast": forecast,
        "history": history,
        "missing": missing,
        "model": "HistGradientBoostingRegressor · MAE",
    }
