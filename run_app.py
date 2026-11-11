"""Start the local application, installing dependencies in a project environment if needed."""

import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 11):
        print("Нужен Python 3.11 или новее: https://www.python.org/downloads/")
        return 1
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONUNBUFFERED"] = "1"
    folder = ROOT / ".app-venv"
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Создаём окружение приложения…", flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    probe = subprocess.run(
        [str(python), "-c", "import numpy, pandas, sklearn, threadpoolctl, certifi, openpyxl"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode:
        print(
            "Первый запуск — устанавливаем библиотеки. Нужен интернет, это может занять несколько минут.",
            flush=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", ".[app]"],
            cwd=ROOT,
            check=True,
        )
    try:
        return subprocess.call(
            [str(python), "-m", "bakery_forecast.webapp", *sys.argv[1:]],
            cwd=ROOT,
            env=environment,
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Не удалось запустить приложение: {exc}")
        print(
            "Проверьте установку Python и доступ к интернету при первом запуске. Инструкция: docs/local_app.md"
        )
        raise SystemExit(1)
