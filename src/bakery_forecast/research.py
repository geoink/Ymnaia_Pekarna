"""Post-hoc robustness study. It does not replace the original frozen evaluation."""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .config import FEATURES, SEED, TEST_END, TEST_START, WARMUP_DAYS
from .data import daily_panel, read_transactions, write_json
from .experiment import evaluate_window
from .features import baseline, make_features
from .metrics import paired_day_bootstrap, regression_metrics
from .model import fit_models, predict_candidates

CALENDAR_FEATURES = ["product", "dow", "month", "weekend", "annual_sin", "annual_cos", "trend"]
HISTORY_FEATURES = [f for f in FEATURES if f not in CALENDAR_FEATURES] + ["product"]
NAMES = ("lag_7", "weekday_mean_4", "weekday_median_4", "rolling_mean_7",
         "hgb_absolute", "hgb_poisson", "blend_absolute", "calendar_only", "history_only")


def seasonal_scales(history: pd.DataFrame, season=7) -> pd.DataFrame:
    """Calculate training-only scales without compressing unknown calendar days."""
    rows = []
    for product, part in history.groupby("product", observed=True):
        part = part.sort_values("date")
        if not part.date.diff().dropna().eq(pd.Timedelta(days=1)).all():
            raise ValueError("Scale input must use a complete daily calendar")
        difference = (part.y - part.y.shift(season)).dropna()
        rows.append({"product": str(product), "mae_scale": difference.abs().mean(),
                     "mse_scale": (difference ** 2).mean(), "scale_pairs": len(difference)})
    return pd.DataFrame(rows).set_index("product")


def scaled_metrics(predictions, name, scales):
    rows = []
    for product, part in predictions.groupby("product", observed=True):
        error = part[name].to_numpy() - part.y.to_numpy()
        mae_scale, mse_scale = scales.loc[str(product), ["mae_scale", "mse_scale"]]
        rows.append({"product": str(product),
                     "mase": np.mean(abs(error)) / mae_scale if mae_scale > 0 else np.nan,
                     "rmsse": np.sqrt(np.mean(error ** 2) / mse_scale) if mse_scale > 0 else np.nan})
    table = pd.DataFrame(rows)
    return {"macro_mase_7": float(table.mase.mean()), "macro_rmsse_7": float(table.rmsse.mean()),
            "scaled_products": int(table.mase.notna().sum())}


def fit_ablation(training, evaluation, columns):
    model = HistGradientBoostingRegressor(
        loss="absolute_error", learning_rate=0.06, max_iter=250, max_leaf_nodes=15,
        min_samples_leaf=20, l2_regularization=5.0, early_stopping=False,
        categorical_features=["product"], random_state=SEED,
    )
    with threadpool_limits(limits=1):
        model.fit(training[columns], training.y)
        return np.maximum(0, model.predict(evaluation[columns]))


def run_research(raw_path: Path, root: Path):
    root = Path(root)
    folder = root / "reports/research"
    folder.mkdir(parents=True, exist_ok=True)
    tx, audit = read_transactions(raw_path)
    panel = daily_panel(tx)
    features = make_features(panel)
    features = features[features.date >= features.date.min() + pd.Timedelta(days=WARMUP_DAYS)]
    windows = pd.date_range("2021-09-01", "2022-08-01", freq="MS")
    months, predictions = [], []
    for start, end in zip(windows[:-1], windows[1:]):
        print(f"Exploratory rolling origin: {start.date()} .. {end.date()}", flush=True)
        train = features[(features.date < start) & features.y.notna()]
        evaluation = features[(features.date >= start) & (features.date < end) & features.y.notna()]
        predicted = evaluation[["date", "product", "y"]].copy()
        for name, values in predict_candidates(evaluation, fit_models(train)).items():
            predicted[name] = values
        fallback = baseline(evaluation, "weekday_mean_4")
        predicted["weekday_median_4"] = evaluation.weekday_median_4.fillna(pd.Series(fallback, index=evaluation.index))
        predicted["rolling_mean_7"] = evaluation.mean_7.fillna(pd.Series(fallback, index=evaluation.index))
        predicted["calendar_only"] = fit_ablation(train, evaluation, CALENDAR_FEATURES)
        predicted["history_only"] = fit_ablation(train, evaluation, HISTORY_FEATURES)
        scales = seasonal_scales(panel[panel.date < start])
        predicted["window"] = str(start.date())
        predictions.append(predicted)
        for name in NAMES:
            months.append({"window": str(start.date()), "model": name,
                           **regression_metrics(predicted.y, predicted[name]),
                           **scaled_metrics(predicted, name, scales)})
    monthly = pd.DataFrame(months)
    all_predictions = pd.concat(predictions, ignore_index=True)
    aggregated = []
    for name in NAMES:
        part = monthly[monthly.model.eq(name)]
        aggregated.append({"model": name, **regression_metrics(all_predictions.y, all_predictions[name]),
                           "mean_month_wape_pct": float(part.wape_pct.mean()),
                           "worst_month_wape_pct": float(part.wape_pct.max()),
                           "mean_macro_mase_7": float(part.macro_mase_7.mean()),
                           "mean_macro_rmsse_7": float(part.macro_rmsse_7.mean())})
    aggregate = pd.DataFrame(aggregated).sort_values("wape_pct")
    table = monthly.pivot(index="window", columns="model", values="wape_pct")
    wins = {name: int((table.hgb_absolute < table[name]).sum())
            for name in ("lag_7", "weekday_mean_4", "weekday_median_4", "rolling_mean_7")}
    # Same exposed test, recomputed only to extend diagnostics; no new model selection.
    original_test = evaluate_window(features, tx, TEST_START, TEST_END)
    interval_rows = []
    for reference in ("lag_7", "weekday_mean_4"):
        for block in (3, 7, 14):
            interval_rows.append({"reference": reference, **paired_day_bootstrap(
                original_test, "hgb_absolute", reference, repeats=2000, block_days=block)})
    scales = seasonal_scales(panel[panel.date < pd.Timestamp(TEST_START)])
    test_scaled = [{"model": name, **scaled_metrics(original_test, name, scales)}
                   for name in ("lag_7", "weekday_mean_4", "hgb_absolute", "hgb_poisson")]
    summary = {"design": "post-hoc exploratory analysis; original test already exposed",
               "original_model_unchanged": "hgb_absolute", "monthly_windows": len(monthly.window.unique()),
               "backtest_rows": len(all_predictions), "start": str(windows[0].date()),
               "end_exclusive": str(windows[-1].date()), "data_sha256": audit["sha256"],
               "monthly_wins_hgb_absolute": wins, "aggregate": aggregate.to_dict(orient="records"),
               "bootstrap_sensitivity": interval_rows, "original_test_scaled_metrics": test_scaled}
    monthly.to_csv(folder / "rolling_origin_metrics.csv", index=False)
    aggregate.to_csv(folder / "aggregate_metrics.csv", index=False)
    pd.DataFrame(interval_rows).to_csv(folder / "bootstrap_sensitivity.csv", index=False)
    pd.DataFrame(test_scaled).to_csv(folder / "test_scaled_metrics.csv", index=False)
    write_json(folder / "summary.json", summary)
    make_research_report(summary, monthly, folder)
    return summary


def make_research_report(summary, monthly, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(11, 4.8))
    for name, label in [("hgb_absolute", "Бустинг MAE"), ("lag_7", "Неделю назад"),
                        ("weekday_median_4", "Медиана 4 недель"), ("weekday_mean_4", "Среднее 4 недель")]:
        data = monthly[monthly.model.eq(name)]
        ax.plot(pd.to_datetime(data.window), data.wape_pct, marker="o", label=label)
    ax.set(title="Дополнительная проверка на 11 месячных окнах", ylabel="WAPE, %")
    ax.legend(ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(folder / "rolling_origin.png", dpi=160)
    plt.close(fig)
    rows = ["# Дополнительный эксперимент", "",
            "Это ретроспективное исследование после просмотра исходного теста. Оно расширяет "
            "диагностику, но не создаёт новый независимый тест и не меняет основной результат.", "",
            f"{summary['monthly_windows']} месячных окон: сентябрь 2021 — июль 2022. "
            "На старте каждого месяца модель переобучается только на предыдущей истории. "
            "Прогнозы однодневные, предыдущие факты внутри месяца доступны для лагов.", "",
            "| Метод | Объединённый WAPE | Средний MASE₇ по месяцам и товарам | Средний RMSSE₇ |",
            "|---|---:|---:|---:|"]
    for row in summary["aggregate"]:
        rows.append(f"| {row['model']} | {row['wape_pct']:.2f}% | {row['mean_macro_mase_7']:.3f} | {row['mean_macro_rmsse_7']:.3f} |")
    rows.extend(["", "Знаменатели MASE/RMSSE считаются только по обучающим данным отдельно для "
                 "каждого товара, сезонный шаг 7 календарных дней. Пары с пропусками не используются. "
                 "Сначала усредняем по товарам, затем по месяцам. WAPE объединён по всем наблюдениям. "
                 "Это разные способы взвешивания, и их ранжирование может различаться.", "",
                 "## Стабильность относительно простых правил", ""])
    for name, wins in summary["monthly_wins_hgb_absolute"].items():
        rows.append(f"- Бустинг MAE лучше `{name}` в {wins} из {summary['monthly_windows']} окон.")
    rows.extend(["", "![Проверка по месяцам](rolling_origin.png)", "",
                 "## Исключение групп признаков", "",
                 "`calendar_only` использует только товар и календарь. `history_only` использует товар, "
                 "лаги и исторические статистики без явных календарных полей. Параметры бустинга "
                 "одинаковы. Разность ошибок показывает вклад группы в данной конфигурации, "
                 "но не доказывает причинное влияние отдельного признака.", "",
                 "## Неопределённость исходного результата", "",
                 "На уже известном тесте повторён блочный bootstrap разности WAPE (MAE-бустинг минус "
                 "baseline) с блоками 3, 7 и 14 календарных дней. Отрицательный интервал благоприятен "
                 "для бустинга. Это приближённые интервалы короткого неоднородного периода.", "",
                 "| Baseline | Длина блока | 95%-интервал разности WAPE, п.п. |", "|---|---:|---:|"])
    for row in summary["bootstrap_sensitivity"]:
        rows.append(f"| {row['reference']} | {row['block_days']} | [{row['low_pp']:.2f}; {row['high_pp']:.2f}] |")
    rows.extend(["", "Исследование не учитывает скрытый спрос, мощность производства и реальную "
                 "стоимость списаний. Новые варианты нельзя объявлять подтверждённо лучшими на "
                 "августе–сентябре после просмотра этого периода. Для следующей версии нужен "
                 "заранее зафиксированный протокол и свежие данные.", ""])
    (folder / "results.md").write_text("\n".join(rows), encoding="utf-8")
