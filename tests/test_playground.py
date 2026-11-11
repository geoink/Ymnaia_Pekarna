"""Custom-data application: parsing, calendar assumptions and real model evaluation."""

import io
import json

import numpy as np
import pandas as pd
import pytest

from bakery_forecast import playground
from bakery_forecast.webapp import WEB


@pytest.fixture
def sales():
    table = playground.read_upload((WEB / "demo.csv").read_bytes(), "demo.csv")
    return playground.normalize_sales(table, playground.suggest_columns(table))[0]


def test_csv_cp1251_decimal_comma_and_corrections():
    content = "Дата;Товар;Продано\n01.06.2026;Багет;2,5\n01.06.2026;Багет;-1\n02.06.2026;Багет;0\n"
    table = playground.read_upload(content.encode("cp1251"), "sales.csv")
    sales, audit = playground.normalize_sales(table, playground.suggest_columns(table))
    assert sales.quantity.tolist() == [1.5, 0]
    assert audit["combined_rows"] == 1
    assert audit["negative_rows"] == 1


def test_excel_first_sheet_native_dates_and_manual_columns():
    raw = pd.DataFrame({"Когда": [pd.Timestamp("2026-07-01")], "Изделие": ["Слойка"], "Штук": [25]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        raw.to_excel(writer, index=False, sheet_name="Продажи")
        pd.DataFrame({"ignored": ["data"]}).to_excel(writer, index=False, sheet_name="Заметки")
    table = playground.read_upload(buffer.getvalue(), "sales.xlsx")
    sales, audit = playground.normalize_sales(
        table, {"date": "Когда", "product": "Изделие", "quantity": "Штук"}
    )
    assert sales.date.item() == pd.Timestamp("2026-07-01")
    assert sales.quantity.item() == 25
    assert audit["products"] == 1


@pytest.mark.parametrize(
    "date,product,quantity",
    [
        ("2026-02-30", "Багет", "1"),
        ("01/02/2026", "Багет", "1"),
        ("2026-06-01", "", "1"),
        ("2026-06-01", "Багет", "три"),
        ("2026-06-01", "Багет", "inf"),
        ("2026-06-01", "Багет", ""),
    ],
)
def test_invalid_cells_show_source_row(date, product, quantity):
    table = pd.DataFrame({"date": [date], "product": [product], "quantity": [quantity]})
    with pytest.raises(ValueError, match="строки 2"):
        playground.normalize_sales(table, playground.suggest_columns(table))


def test_upload_bounds_and_mapping():
    for content, filename in [
        (b"", "x.csv"),
        (b"bad", "x.xls"),
        (b"bad", "x.xlsx"),
        (b"x" * (playground.MAX_FILE_BYTES + 1), "x.csv"),
    ]:
        with pytest.raises(ValueError):
            playground.read_upload(content, filename)
    table = pd.DataFrame({"date": ["2026-01-01"], "product": ["Багет"], "quantity": [1]})
    with pytest.raises(ValueError, match="разных"):
        playground.normalize_sales(
            table, {"date": "date", "product": "product", "quantity": "product"}
        )
    table.loc[1] = ["2019-01-01", "Багет", 1]
    with pytest.raises(ValueError, match="пяти лет"):
        playground.normalize_sales(table, playground.suggest_columns(table))


def test_missing_policy_does_not_invent_shop_days_or_prelaunch_sales(sales):
    partial = sales[~sales.date.eq("2026-07-20")].copy()
    partial = partial[~(partial["product"].eq("Багет") & partial.date.eq("2026-07-21"))]
    partial = partial[~(partial["product"].eq("Круассан") & partial.date.lt("2026-07-12"))]
    products = sorted(partial["product"].unique())
    unknown = playground.prepare_features(partial, products, "unknown")[0]
    zeros = playground.prepare_features(partial, products, "zero")[0]
    for frame in (unknown, zeros):
        assert frame.loc[frame.date.eq("2026-07-20"), "y"].isna().all()
        assert (
            frame.loc[frame["product"].eq("Круассан") & frame.date.lt("2026-07-12"), "y"]
            .isna()
            .all()
        )
    missing_item = unknown.date.eq("2026-07-21") & unknown["product"].eq("Багет")
    assert unknown.loc[missing_item, "y"].isna().all()
    assert zeros.loc[missing_item, "y"].item() == 0


def test_custom_products_real_fit_temporal_split_and_forecast(sales, monkeypatch):
    sales["product"] = sales["product"].replace({"Багет": "Мой хлеб", "Круассан": "Моя слойка"})
    fits = []
    original = playground.fit_models

    def spy(frame, **kwargs):
        fits.append(frame.copy())
        return original(frame, **kwargs)

    monkeypatch.setattr(playground, "fit_models", spy)
    result = playground.run_playground(sales, ["Мой хлеб", "Моя слойка"])
    assert result["target_date"] == "2026-09-29"
    assert result["check_rows"] == 28
    assert fits[0].date.max() < pd.Timestamp(result["check_start"])
    assert fits[1].date.max() == pd.Timestamp(result["last_date"])
    assert set(row["product"] for row in result["forecast"]) == {"Мой хлеб", "Моя слойка"}
    assert all(row["forecast"] >= 0 and np.isfinite(row["forecast"]) for row in result["forecast"])
    assert len(result["history"]) == 112
    assert result["metrics"]["hgb_absolute"]["n"] == 28
    json.dumps(result, allow_nan=False)


def test_all_zero_sales_are_valid_and_wape_is_undefined(sales):
    sales.quantity = 0.0
    result = playground.run_playground(sales, ["Багет"])
    assert result["metrics"]["hgb_absolute"]["wape_pct"] is None
    assert result["forecast"][0]["forecast"] == 0
    json.dumps(result, allow_nan=False)


def test_insufficient_history_and_selection_errors(sales):
    with pytest.raises(ValueError, match="84"):
        playground.prepare_features(sales[sales.date < "2026-07-01"], ["Багет"], "unknown")
    with pytest.raises(ValueError, match="хотя бы один"):
        playground.prepare_features(sales, [], "unknown")
    with pytest.raises(ValueError, match="не совпадает"):
        playground.prepare_features(sales, ["Неизвестный товар"], "unknown")
    sparse = sales[~(sales["product"].eq("Багет") & sales.date.ge("2026-09-15"))]
    with pytest.raises(ValueError, match="проверки"):
        playground.prepare_features(sparse, ["Багет"], "unknown")
