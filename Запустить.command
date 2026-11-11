#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Установите Python 3.11 или новее с https://www.python.org/downloads/'
  read -r -p 'Нажмите Enter для закрытия…'
  exit 1
fi
python3 run_app.py "$@"
status=$?
if [ "$status" -ne 0 ]; then
  read -r -p 'Нажмите Enter для закрытия…'
fi
exit "$status"
