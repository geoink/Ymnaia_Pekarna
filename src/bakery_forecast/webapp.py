"""Small loopback-only website for uploading sales and running a local ML experiment."""

import argparse
import base64
import binascii
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
import webbrowser

from .playground import (
    MAX_FILE_BYTES,
    normalize_sales,
    product_summary,
    read_upload,
    run_playground,
    suggest_columns,
)


WEB = Path(__file__).with_name("web")
MAX_REQUEST_BYTES = 12 * 1024 * 1024


class PlaygroundState:
    def __init__(self):
        self.uploads = {}
        self.lock = threading.Lock()
        self.training = threading.Lock()

    def expire(self):
        with self.lock:
            now = time.monotonic()
            self.uploads = {
                key: value for key, value in self.uploads.items() if now - value["created"] < 3600
            }

    def add(self, table, filename, demo=False):
        with self.lock:
            now = time.monotonic()
            self.uploads = {
                key: value for key, value in self.uploads.items() if now - value["created"] < 3600
            }
            if len(self.uploads) >= 4:
                self.uploads.pop(next(iter(self.uploads)))
            key = secrets.token_urlsafe(24)
            self.uploads[key] = {"table": table, "filename": filename, "demo": demo, "created": now}
        preview = json.loads(table.head(5).to_json(orient="records", date_format="iso"))
        return {
            "id": key,
            "filename": filename,
            "demo": demo,
            "rows": len(table),
            "columns": list(table.columns),
            "suggested": suggest_columns(table),
            "preview": preview,
        }

    def get(self, key):
        if not isinstance(key, str):
            raise ValueError("Сначала загрузите файл с продажами.")
        with self.lock:
            upload = self.uploads.get(key)
            if upload is None or time.monotonic() - upload["created"] > 3600:
                raise ValueError("Срок хранения таблицы истёк. Загрузите файл ещё раз.")
            return upload.copy()

    def prepare(self, key, columns):
        upload = self.get(key)
        sales, audit = normalize_sales(upload["table"], columns)
        with self.lock:
            if key not in self.uploads:
                raise ValueError("Загрузите файл ещё раз.")
            self.uploads[key]["sales"] = sales
        return {"audit": audit, "products": product_summary(sales), "demo": upload["demo"]}


class PlaygroundHandler(BaseHTTPRequestHandler):
    server_version = "BakeryLocal/1.0"

    def __init__(self, *args, state, **kwargs):
        self.state = state
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, data, status=200):
        self.send_bytes(
            json.dumps(data, ensure_ascii=False, allow_nan=False).encode(),
            "application/json; charset=utf-8",
            status,
        )

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self):
        if not self.valid_host():
            self.send_json({"error": "Откройте приложение по локальному адресу из Терминала."}, 403)
            return
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/demo.csv": ("demo.csv", "text/csv; charset=utf-8"),
            "/template.csv": ("template.csv", "text/csv; charset=utf-8"),
        }
        if self.path == "/health":
            self.send_json({"status": "ok"})
        elif self.path in files:
            name, mime = files[self.path]
            self.send_bytes((WEB / name).read_bytes(), mime)
        else:
            self.send_json({"error": "Страница не найдена."}, 404)

    def do_POST(self):
        origin = self.headers.get("Origin")
        allowed_origin = f"http://{self.headers.get('Host')}"
        if not self.valid_host() or (origin and origin != allowed_origin):
            self.send_json({"error": "Запрос разрешён только из окна локального приложения."}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_REQUEST_BYTES:
                self.send_json(
                    {"error": "Размер запроса слишком большой. Выберите файл до 8 МБ."}, 413
                )
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.send_json({"error": "Ожидается запрос JSON."}, 415)
                return
            self.connection.settimeout(30)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Некорректный запрос. Обновите страницу.")
            if self.path == "/api/inspect":
                encoded, filename = payload.get("content"), payload.get("filename")
                if (
                    not isinstance(encoded, str)
                    or not isinstance(filename, str)
                    or len(filename) > 255
                ):
                    raise ValueError("Выберите файл CSV или Excel.")
                content = base64.b64decode(encoded, validate=True)
                if len(content) > MAX_FILE_BYTES:
                    raise ValueError("Выберите файл до 8 МБ.")
                result = self.state.add(read_upload(content, filename), filename)
            elif self.path == "/api/demo":
                result = self.state.add(
                    read_upload((WEB / "demo.csv").read_bytes(), "demo.csv"),
                    "Учебные продажи · 120 дней",
                    demo=True,
                )
            elif self.path == "/api/prepare":
                columns = payload.get("columns")
                if not isinstance(columns, dict):
                    raise ValueError("Выберите столбцы даты, товара и количества.")
                result = self.state.prepare(payload.get("id"), columns)
            elif self.path == "/api/train":
                upload = self.state.get(payload.get("id"))
                if "sales" not in upload:
                    raise ValueError("Сначала прочитайте таблицу и проверьте названия столбцов.")
                if not self.state.training.acquire(blocking=False):
                    self.send_json(
                        {"error": "Другой расчёт ещё выполняется. Дождитесь его завершения."}, 409
                    )
                    return
                try:
                    result = run_playground(
                        upload["sales"], payload.get("products"), payload.get("missing", "unknown")
                    )
                    result["demo"] = upload["demo"]
                finally:
                    self.state.training.release()
            else:
                self.send_json({"error": "Действие не найдено."}, 404)
                return
            self.send_json(result)
        except (ValueError, TypeError, binascii.Error) as exc:
            self.send_json({"error": str(exc)}, 400)
        except (TimeoutError, ConnectionError):
            self.send_json(
                {"error": "Передача файла прервана. Попробуйте загрузить его ещё раз."}, 408
            )
        except Exception:
            self.send_json(
                {
                    "error": "Расчёт не завершился. Проверьте таблицу или попробуйте демонстрационный пример."
                },
                500,
            )


class PlaygroundServer(ThreadingHTTPServer):
    def __init__(self, port):
        self.state = PlaygroundState()
        super().__init__(("127.0.0.1", port), partial(PlaygroundHandler, state=self.state))

    def service_actions(self):
        self.state.expire()


def create_server(port=8765):
    return PlaygroundServer(port)


def main():
    parser = argparse.ArgumentParser(description="Проверка прогноза пекарни в локальном браузере")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Порт должен быть в диапазоне 0–65535.")
    try:
        server = create_server(args.port)
    except OSError as exc:
        parser.exit(1, f"Не удалось открыть порт {args.port}. Попробуйте --port 8766. {exc}\n")
    address = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Умная пекарня открыта по адресу {address}", flush=True)
    print(
        "Файлы обрабатываются в памяти этого компьютера. Для завершения нажмите Ctrl+C.", flush=True
    )
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
