"""Portable commands: download, run, forecast."""

import argparse
from pathlib import Path

from .config import RAW_NAME
from .data import download_data


def main():
    parser = argparse.ArgumentParser(description="Bakery next-day sales forecasting")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="Download the original Kaggle CSV with SHA-256 verification")
    download.add_argument("--output", type=Path, default=Path("data/raw") / RAW_NAME)
    run = sub.add_parser("run", help="Run the fixed evaluation protocol and refit a deployment model")
    run.add_argument("--data", type=Path, default=Path("data/raw") / RAW_NAME)
    run.add_argument("--output", type=Path, default=Path("."))
    research = sub.add_parser("research", help="Run post-hoc rolling-origin, ablation and uncertainty checks")
    research.add_argument("--data", type=Path, default=Path("data/raw") / RAW_NAME)
    research.add_argument("--output", type=Path, default=Path("."))
    forecast = sub.add_parser("forecast", help="Predict the calendar day after the last transaction")
    forecast.add_argument("--data", type=Path, default=Path("data/raw") / RAW_NAME)
    forecast.add_argument("--model", type=Path, default=Path("models/forecast.joblib"))
    forecast.add_argument("--output", type=Path, default=Path("reports/next_day_forecast.csv"))
    args = parser.parse_args()
    if args.command == "download":
        print(download_data(args.output))
    elif args.command == "run":
        from .experiment import run_experiment
        if not args.data.exists():
            parser.error("CSV not found. Run 'bakery download' or supply --data.")
        summary = run_experiment(args.data, args.output)
        print(f"Finished. Selected model: {summary['selected_model']}")
        for row in summary["test_metrics"]:
            print(f"{row['model']:<20} WAPE={row['wape_pct']:.2f}% MAE={row['mae']:.2f}")
    elif args.command == "research":
        from .research import run_research
        summary = run_research(args.data, args.output)
        print(f"Research completed: {summary['monthly_windows']} windows. Original model unchanged.")
    elif args.command == "forecast":
        from .experiment import predict_next_day
        forecast = predict_next_day(args.data, args.model)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        forecast.to_csv(args.output, index=False)
        print(forecast.to_string(index=False))
        print("Assumes the shop is open. Rounded forecasts are not cost-optimized production plans.")


if __name__ == "__main__":
    main()
