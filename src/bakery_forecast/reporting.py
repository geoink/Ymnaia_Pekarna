"""Static research charts. Every plotted forecast comes from the saved experiment."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LABELS = {"lag_7": "Неделю назад", "weekday_mean_4": "Среднее 4 недель",
          "hgb_absolute": "Бустинг MAE", "hgb_poisson": "Бустинг Poisson", "blend_absolute": "Бустинг + среднее"}


def write_results(summary, audit, economics, root):
    selected = summary["selected_model"]
    metrics = pd.DataFrame(summary["test_metrics"]).set_index("model")
    validation = pd.DataFrame(summary["validation_metrics"]).set_index("model")
    lines = [
        "# Результаты воспроизводимого эксперимента", "",
        f"Источник: French Bakery Daily Sales. SHA-256: `{audit['sha256']}`.", "",
        f"Исходных строк: **{audit['raw_rows']:,}**. Дней с записями: **{audit['observed_dates']}**. "
        f"Период: {audit['first_date']} — {audit['last_date']}. В эксперименте восемь товаров.", "",
        "## Схема проверки", "",
        "Две расширяющиеся выборки: обучение до 01.06.2022, проверка на июне; "
        "обучение до 01.07.2022, проверка на июле. Основную модель выбираем по суммарному WAPE "
        "двух проверок. Затем переобучаем на данных до 01.08.2022 и оцениваем август–сентябрь.", "",
        f"Модель, выбранная до теста: **{selected}**. Тест: **{summary['test_observed_days']}** "
        f"дней с записями, **{summary['test_rows']}** пар «день–товар».", "",
        "Прогноз формируется каждый вечер на следующий день. Фактические продажи прошедших "
        "дней теста доступны для лагов, веса модели в течение теста не меняются. Это серия "
        "однодневных прогнозов, а не прогноз сразу на два месяца.", "",
        "## Качество", "", "| Модель | WAPE, валидация | WAPE, тест | MAE, тест, шт. |",
        "|---|---:|---:|---:|",
    ]
    for name in metrics.index:
        lines.append(f"| {LABELS[name]} (`{name}`) | {validation.loc[name, 'wape_pct']:.2f}% | "
                     f"{metrics.loc[name, 'wape_pct']:.2f}% | {metrics.loc[name, 'mae']:.2f} |")
    ci = summary["ml_minus_baseline_wape_ci"]
    relative_vs_week = 100 * (1 - metrics.loc[summary['best_ml'], 'wape_pct'] / metrics.loc['lag_7', 'wape_pct'])
    lines.extend([
        "", f"Лучшая ML-модель по валидации: `{summary['best_ml']}`. "
        f"Снижение WAPE относительно выбранного на валидации базового метода "
        f"`{summary['best_baseline']}` на тесте: **{summary['ml_relative_wape_reduction_pct']:.2f}%**. "
        f"Относительно «неделю назад»: **{relative_vs_week:.2f}%**.", "",
        "Все кандидаты показаны для прозрачности. Выбирать другую основную модель по "
        "результатам этого же теста нельзя: для нового выбора понадобится новый период проверки.", "",
        f"Приблизительный 95%-интервал разности WAPE (ML минус выбранный baseline): "
        f"**[{ci['low_pp']:.2f}; {ci['high_pp']:.2f}] п.п.** "
        "Парный блочный bootstrap: 2 000 повторов, блок семь календарных дней. "
        "Интервал относится к данному короткому периоду и не доказывает переносимость на другие пекарни.", "",
        "![Сравнение моделей](figures/model_comparison.png)", "",
        "![Прогнозы на тесте](figures/test_forecast.png)", "",
        "## Сценарная экономика", "",
        "Это расчёт при допущениях, а не наблюдавшийся финансовый результат. Продажи принимаем "
        "за спрос, себестоимость составляет 30/50/70% цены, непроданный товар полностью списывается. "
        "Цена каждого товара — медиана его положительных цен в обучающей истории. "
        "Коэффициент запаса выбирается только на валидации, отдельно для каждого метода и сценария.", "",
        "| Себестоимость | Метод | Коэффициент выпуска | Условные потери на тесте, € |",
        "|---|---|---:|---:|",
    ])
    for row in economics.itertuples():
        if row.model in {summary['best_baseline'], summary['best_ml'], 'lag_7'}:
            lines.append(f"| {row.cost_ratio:.0%} цены | {LABELS[row.model]} | {row.multiplier:.1f} | {row.loss_eur:.2f} |")
    lines.extend([
        "", "![Сценарная экономика](figures/economic_scenarios.png)", "",
        "## Ограничения", "",
        "- Продажи ограничены наличием товара. Время исчерпания запасов, фактический выпуск и списания неизвестны.",
        "- Дни без транзакций исключены из оценки и остаются пропусками в истории. Причина отсутствия записей неизвестна.",
        "- Отсутствие товара в чеках в день с другими продажами считаем нулём. Это допущение требует проверки в реальной пекарне.",
        "- Отрицательные количества учитываем как корректировки. Повторяющиеся строки сохраняем: идентификатор строки продажи отсутствует.",
        "- Одна пекарня, восемь товаров, исторический период 2021–2022. Результат нельзя автоматически переносить на 2026 год.",
        "- Агрегированный WAPE сильнее зависит от массовых товаров. См. отдельные товары и месяцы в CSV-отчётах.",
        "", "## Следующий шаг", "",
        "Пилот с владельцем: фиксировать выпуск, остатки, списания и время отсутствия товара. "
        "Сначала сравнить прогнозы без изменения работы, затем проверить план выпуска при "
        "ограничениях печи, персонала и ассортименте. Финансовый эффект измерять по фактическим данным.", "",
        f"Среда запуска: Python {summary['python']}; " + ", ".join(f"{key} {value}" for key, value in summary['packages'].items()) + ".", "",
    ])
    (root / "reports/results.md").write_text("\n".join(lines), encoding="utf-8")


def create_figures(panel, validation, test, summary, economics, root):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "#fffdf8", "axes.facecolor": "#fffdf8",
                         "axes.titleweight": "bold", "axes.titlepad": 14})
    folder = root / "reports/figures"

    def save(fig, name):
        fig.savefig(folder / name, dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)

    daily = panel.groupby("date").y.sum(min_count=1)
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(daily.index, daily, color="#8b5e3c", linewidth=0.9, alpha=0.5, label="Продажи за день")
    ax.plot(daily.index, daily.rolling(28, min_periods=14).mean(), color="#12645c", linewidth=2, label="Среднее за 28 дней")
    ax.axvline(pd.Timestamp("2022-06-01"), linestyle="--", color="#d29330", label="Начало валидации")
    ax.axvline(pd.Timestamp(summary["test_start"]), linestyle="--", color="#ad433b", label="Начало теста")
    ax.set(title="Продажи восьми выбранных товаров", ylabel="Единиц в день")
    ax.legend(fontsize=9, ncol=2)
    fig.autofmt_xdate()
    save(fig, "sales_history.png")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, key, title in zip(axes, ["validation_metrics", "test_metrics"], ["Валидация: июнь–июль", "Тест: август–сентябрь"]):
        table = pd.DataFrame(summary[key]).sort_values("wape_pct", ascending=False)
        colors = ["#12645c" if name == summary["selected_model"] else "#cda47c" for name in table.model]
        bars = ax.barh([LABELS[name] for name in table.model], table.wape_pct, color=colors)
        ax.bar_label(bars, fmt="%.1f%%", padding=4)
        ax.set(title=title, xlabel="WAPE, % (меньше — лучше)", xlim=(0, table.wape_pct.max() * 1.2))
    fig.tight_layout()
    save(fig, "model_comparison.png")

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, product in zip(axes, ["TRADITIONAL BAGUETTE", "CROISSANT"]):
        part = test[test['product'].eq(product)].set_index("date").reindex(pd.date_range(test.date.min(), test.date.max()))
        ax.plot(part.index, part.y, color="#2e2823", linewidth=1.7, label="Фактические продажи")
        ax.plot(part.index, part[summary["best_baseline"]], color="#bd8a4b", linestyle="--", label="Базовый прогноз")
        ax.plot(part.index, part[summary["best_ml"]], color="#12645c", linewidth=1.5, label="ML-прогноз")
        ax.set(title=product, ylabel="Единиц")
    axes[0].legend(fontsize=9, ncol=3)
    fig.autofmt_xdate()
    fig.tight_layout()
    save(fig, "test_forecast.png")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    x = np.arange(3)
    for offset, name, color in [(-0.18, summary["best_baseline"], "#bd8a4b"), (0.18, summary["best_ml"], "#12645c")]:
        part = economics[economics.model.eq(name)].sort_values("cost_ratio")
        bars = ax.bar(x + offset, part.loss_eur, width=0.36, label=LABELS[name], color=color)
        ax.bar_label(bars, fmt="%.0f", padding=3)
    ax.set(xticks=x, xticklabels=["30% цены", "50% цены", "70% цены"],
           ylabel="Условные потери за тестовый период, €",
           title="Сценарий: себестоимость и цена ошибки", xlabel="Предполагаемая себестоимость единицы")
    ax.legend()
    ax.text(0, -0.25, "Сценарная оценка: продажи приняты за спрос. Это не измеренная экономия пекарни.",
            transform=ax.transAxes, fontsize=10)
    save(fig, "economic_scenarios.png")

    fig, ax = plt.subplots(figsize=(9, 4))
    weekday = panel[panel.y.notna()].assign(dow=lambda x: x.date.dt.day_of_week).groupby(["date", "dow"]).y.sum().groupby("dow").mean()
    ax.bar(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"], weekday.reindex(range(7)), color="#12645c")
    ax.set(title="Средние продажи по дням недели", ylabel="Единиц, восемь товаров")
    ax.text(0, -0.2, "Только дни с записями. График описательный, использует весь период.", transform=ax.transAxes, fontsize=9)
    save(fig, "weekday_sales.png")
