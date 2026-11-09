"""Source download, explicit transaction cleaning, and calendar completion."""

import hashlib
import io
import json
import ssl
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import certifi

from .config import DOWNLOAD_URL, EXPECTED_SHA256, PRODUCTS, RAW_NAME, SOURCE_URL


def download_data(destination: Path) -> Path:
    """Download only the known CSV and verify its digest; never unpack arbitrary paths."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != EXPECTED_SHA256:
            raise ValueError("Existing CSV differs from the documented source. Use --data explicitly for other data.")
        return destination
    request = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "bakery-coursework/0.1"})
    context = ssl.create_default_context()
    context.load_verify_locations(certifi.where())
    try:
        with urllib.request.urlopen(request, timeout=90, context=context) as response:
            archive = response.read(25_000_001)
        if len(archive) > 25_000_000:
            raise ValueError("Unexpected download size")
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            info = source.getinfo(RAW_NAME)
            if info.file_size > 50_000_000:
                raise ValueError("Unexpected CSV size")
            raw = source.read(RAW_NAME)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise RuntimeError(f"Download failed. Download {RAW_NAME} manually from {SOURCE_URL}: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Source SHA-256 changed. Review the source before updating the expected checksum.")
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return destination


def read_transactions(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path)
    required = {"date", "article", "Quantity", "unit_price", "time", "ticket_number"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing columns: {sorted(required - set(raw.columns))}")
    data = raw[list(sorted(required))].copy()
    audit = {"raw_rows": len(raw), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    audit["repeated_content_rows_retained"] = int(data.duplicated().sum())
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data["quantity"] = pd.to_numeric(data.pop("Quantity"), errors="coerce")
    data["price"] = pd.to_numeric(
        data.pop("unit_price").astype(str).str.replace("€", "", regex=False)
        .str.replace(" ", "", regex=False).str.replace(",", ".", regex=False), errors="coerce"
    )
    data["product"] = data.pop("article").astype("string").str.strip()
    valid = (
        data["date"].notna() & data["product"].notna() & data["product"].ne("")
        & np.isfinite(data["quantity"]) & np.isfinite(data["price"]) & data["price"].ge(0)
    )
    audit["invalid_rows_removed"] = int((~valid).sum())
    data = data.loc[valid].copy()
    if data.empty:
        raise ValueError("No valid transactions")
    audit.update({
        "negative_quantity_rows_retained": int(data.quantity.lt(0).sum()),
        "zero_quantity_rows_retained": int(data.quantity.eq(0).sum()),
        "zero_price_rows_retained": int(data.price.eq(0).sum()),
        "observed_dates": int(data.date.nunique()), "products_in_source": int(data['product'].nunique()),
        "first_date": str(data.date.min().date()), "last_date": str(data.date.max().date()),
    })
    calendar = pd.date_range(data.date.min(), data.date.max())
    audit["dates_without_any_transactions"] = [str(x.date()) for x in calendar.difference(data.date.unique())]
    return data, audit


def daily_panel(transactions: pd.DataFrame, products=PRODUCTS, end_date=None) -> pd.DataFrame:
    """Missing shop dates stay unknown; missing SKU on an observed shop date is assumed zero."""
    products = tuple(products)
    missing = set(products) - set(transactions["product"])
    if missing:
        raise ValueError(f"Products absent from source: {sorted(missing)}")
    first, last = transactions.date.min(), transactions.date.max()
    end = last if end_date is None else pd.Timestamp(end_date)
    if end < last:
        raise ValueError("end_date cannot precede the latest transaction")
    index = pd.MultiIndex.from_product([pd.date_range(first, end), products], names=["date", "product"])
    selected = transactions[transactions["product"].isin(products)]
    quantity = selected.groupby(["date", "product"])["quantity"].sum()
    panel = quantity.reindex(index).rename("net_quantity").reset_index()
    panel["shop_observed"] = panel.date.isin(transactions.date.unique())
    panel["product_absence_assumed_zero"] = panel.shop_observed & panel.net_quantity.isna()
    panel.loc[panel.product_absence_assumed_zero, "net_quantity"] = 0.0
    panel["y"] = panel.net_quantity.clip(lower=0)
    return panel.sort_values(["product", "date"]).reset_index(drop=True)


def write_json(path: Path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
