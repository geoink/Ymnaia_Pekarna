"use strict";

const $ = (id) => document.getElementById(id);
const state = { upload: null, prepared: false, busy: false, result: null };
const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const mappings = { date: $("dateColumn"), product: $("productColumn"), quantity: $("quantityColumn") };
const fileMode = location.protocol === "file:";

function dateLabel(value, short = false) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("ru-RU", {
    day: "numeric", month: short ? "short" : "long", ...(short ? {} : { year: "numeric" }),
  });
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function selectedProducts() {
  return [...$("products").querySelectorAll("input:checked")].map((input) => input.value);
}

function updateControls() {
  document.querySelectorAll("button, input, select").forEach((control) => {
    control.disabled = state.busy || fileMode;
  });
  $("trainButton").disabled = state.busy || fileMode || !state.prepared || !selectedProducts().length;
  const count = selectedProducts().length;
  $("selectedCount").textContent = count ? `· ${count}` : "";
  $("selectAll").textContent = count === $("products").children.length ? "Снять выбор" : "Выбрать все";
}

function resetResult() {
  state.result = null;
  $("result").hidden = true;
  $("welcome").hidden = false;
}

function resetPrepared() {
  state.prepared = false;
  $("dataSection").hidden = true;
  $("products").replaceChildren();
  resetResult();
  updateControls();
}

function showError(error) {
  $("error").textContent = error.message || String(error);
  $("error").hidden = false;
}

async function action(message, task) {
  if (state.busy || fileMode) return;
  state.busy = true;
  $("error").hidden = true;
  $("progressText").textContent = message;
  $("progress").hidden = false;
  updateControls();
  try {
    await task();
  } catch (error) {
    showError(error);
  } finally {
    state.busy = false;
    $("progress").hidden = true;
    updateControls();
  }
}

async function api(path, payload) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("Нет связи с приложением. Проверьте, что окно Терминала с моделью открыто, или запустите приложение заново.");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Не удалось выполнить запрос.");
  return result;
}

function renderPreview(upload) {
  const head = element("thead");
  const row = element("tr");
  upload.columns.forEach((name) => row.append(element("th", name)));
  head.append(row);
  const body = element("tbody");
  upload.preview.forEach((record) => {
    const line = element("tr");
    upload.columns.forEach((name) => line.append(element("td", record[name] ?? "—")));
    body.append(line);
  });
  $("previewTable").replaceChildren(head, body);
}

async function acceptUpload(upload) {
  state.upload = upload;
  $("fileLabel").textContent = upload.filename;
  $("demoLabel").hidden = !upload.demo;
  $("mappingSection").hidden = false;
  Object.entries(mappings).forEach(([key, select]) => {
    select.replaceChildren(new Option("Выберите столбец", ""));
    upload.columns.forEach((name) => select.add(new Option(name, name)));
    select.value = upload.suggested[key] || "";
  });
  renderPreview(upload);
  if (Object.values(mappings).every((select) => select.value)) await prepare();
}

function resetUpload() {
  state.upload = null;
  $("mappingSection").hidden = true;
  $("demoLabel").hidden = true;
  $("fileLabel").textContent = "Выберите файл";
  resetPrepared();
}

async function uploadFile(file) {
  if (!file) return;
  await action("Читаем файл…", async () => {
    resetUpload();
    if (!/\.(csv|xlsx)$/i.test(file.name) || !file.size || file.size > 8 * 1024 * 1024) {
      throw new Error("Выберите непустой файл CSV или Excel .xlsx размером до 8 МБ.");
    }
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("Не удалось открыть файл на компьютере."));
      reader.readAsDataURL(file);
    });
    await acceptUpload(await api("/api/inspect", { filename: file.name, content }));
  });
  $("fileInput").value = "";
}

async function prepare() {
  resetPrepared();
  const columns = Object.fromEntries(Object.entries(mappings).map(([key, select]) => [key, select.value]));
  const result = await api("/api/prepare", { id: state.upload.id, columns });
  const audit = result.audit;
  const summary = [[audit.products, "товаров"], [audit.observed_days, "дней с записями"], [audit.rows, "строк"]];
  $("dataSummary").replaceChildren(...summary.map(([value, label]) => {
    const node = element("div");
    node.append(element("strong", number.format(value)), element("span", label));
    return node;
  }));
  const notes = [`${dateLabel(audit.first_date, true)} — ${dateLabel(audit.last_date)}`];
  if (audit.missing_days) notes.push(`Дней без записей: ${audit.missing_days}.`);
  if (audit.combined_rows) notes.push(`Суммировано повторных строк «дата + товар»: ${audit.combined_rows}.`);
  if (audit.negative_rows) notes.push(`Отрицательных корректировок: ${audit.negative_rows}.`);
  if (audit.negative_totals) notes.push(`Дневных итогов ограничено нулём: ${audit.negative_totals}.`);
  $("dataNotes").textContent = notes.join(" ");
  $("products").replaceChildren(...result.products.map((product) => {
    const label = element("label", undefined, "product-option");
    const input = element("input");
    input.type = "checkbox";
    input.value = product.name;
    input.checked = true;
    input.addEventListener("change", () => { resetResult(); updateControls(); });
    label.append(input, element("span", product.name), element("small", `${product.days} дн.`));
    return label;
  }));
  state.prepared = true;
  $("dataSection").hidden = false;
}

const percent = (value) => value === null ? "—" : `${number.format(value)}%`;

function tableRow(values) {
  const row = element("tr");
  values.forEach((value) => row.append(element("td", value)));
  return row;
}

function renderResult(result) {
  state.result = result;
  $("forecastTitle").textContent = dateLabel(result.target_date);
  $("forecastSubtitle").textContent = `Последняя дата файла: ${dateLabel(result.last_date)} · Товаров: ${result.forecast.length}`;
  $("resultDemo").hidden = !result.demo;
  $("forecastRows").replaceChildren(...result.forecast.map((row) => tableRow([
    row.product, number.format(row.forecast), number.format(row.rounded), number.format(row.lag_7),
  ])));
  const total = (key) => number.format(result.forecast.reduce((sum, row) => sum + row[key], 0));
  $("forecastFooter").replaceChildren(tableRow(["Всего", total("forecast"), total("rounded"), total("lag_7")]));
  $("checkDates").textContent = `${dateLabel(result.check_start, true)} — ${dateLabel(result.check_end, true)} · Наблюдений: ${result.check_rows}`;
  const ml = result.metrics.hgb_absolute;
  const base = result.metrics.lag_7;
  $("mlWape").textContent = percent(ml.wape_pct);
  $("baseWape").textContent = percent(base.wape_pct);
  $("mlMae").textContent = `${number.format(ml.mae)} шт.`;
  const comparison = $("comparisonText");
  comparison.classList.toggle("caution", ml.mae > base.mae);
  if (ml.wape_pct === null) {
    comparison.textContent = "В периоде проверки суммарные продажи равны нулю. Сравнивайте MAE: процентная ошибка здесь не определена.";
  } else {
    const difference = base.wape_pct - ml.wape_pct;
    comparison.textContent = Math.abs(difference) < 0.005
      ? "На этой проверке ошибки ML и правила «неделю назад» практически совпали."
      : difference > 0
        ? `Ошибка ML ниже на ${number.format(difference)} п. п. Качество нужно повторно проверять по мере поступления новых продаж.`
        : `Ошибка ML выше на ${number.format(-difference)} п. п. На этом периоде правило «неделю назад» оказалось точнее.`;
  }
  comparison.append(document.createTextNode(` Среднее четырёх недель: WAPE ${percent(result.metrics.weekday_mean_4.wape_pct)}.`));
  $("qualityRows").replaceChildren(...result.products.map((row) => tableRow([
    row.product, percent(row.ml.wape_pct), percent(row.baseline.wape_pct),
    number.format(row.ml.mae), number.format(row.ml.bias_units),
  ])));
  $("chartProduct").replaceChildren(...result.forecast.map((row) => new Option(row.product, row.product)));
  $("welcome").hidden = true;
  $("result").hidden = false;
  renderChart();
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function svgNode(tag, attributes = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderChart() {
  if (!state.result) return;
  const result = state.result;
  const product = $("chartProduct").value;
  const rows = result.history.filter((row) => row.product === product);
  const forecast = result.forecast.find((row) => row.product === product);
  const width = Math.max(340, $("chart").clientWidth);
  const height = 250, left = 42, right = 18, top = 22, bottom = 32;
  const max = Math.max(1, forecast.forecast, ...rows.flatMap((row) => [row.actual ?? 0, row.predicted ?? 0])) * 1.17;
  const x = (index) => left + index / rows.length * (width - left - right);
  const y = (value) => height - bottom - value / max * (height - top - bottom);
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, "font-family": "Arial, sans-serif", "font-size": 10 });
  svg.append(svgNode("title", {}, `${product}: история продаж и прогноз ${number.format(forecast.forecast)} шт.`));
  const checkIndex = rows.findIndex((row) => row.date >= result.check_start);
  if (checkIndex >= 0) svg.append(svgNode("rect", {
    x: x(checkIndex), y: top, width: x(rows.length - 1) - x(checkIndex), height: height - top - bottom, fill: "#e9f0e8",
  }));
  for (let index = 0; index <= 4; index++) {
    const value = index * max / 4;
    svg.append(svgNode("line", { x1: left, x2: width - right, y1: y(value), y2: y(value), stroke: "#dedfd3" }));
    svg.append(svgNode("text", { x: left - 7, y: y(value) + 4, fill: "#6a7267", "text-anchor": "end" }, number.format(Math.round(value))));
  }
  [0, Math.floor(rows.length / 2), rows.length].forEach((index) => {
    svg.append(svgNode("text", {
      x: x(index), y: height - 8, fill: "#6a7267", "text-anchor": index === rows.length ? "end" : index === 0 ? "start" : "middle",
    }, dateLabel(index === rows.length ? result.target_date : rows[index].date, true)));
  });
  [["actual", "#174e3d"], ["predicted", "#b87a38"]].forEach(([key, color]) => {
    let path = "", previous = false;
    rows.forEach((row, index) => {
      if (row[key] === null) { previous = false; return; }
      path += `${previous ? "L" : "M"}${x(index)},${y(row[key])} `;
      previous = true;
      const point = svgNode("circle", { cx: x(index), cy: y(row[key]), r: 2.3, fill: color });
      point.append(svgNode("title", {}, `${dateLabel(row.date)}: ${number.format(row[key])} шт. (${key === "actual" ? "продажи" : "ML"})`));
      svg.append(point);
    });
    const attributes = { d: path, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round" };
    if (key === "predicted") attributes["stroke-dasharray"] = "5 4";
    svg.append(svgNode("path", attributes));
  });
  const point = svgNode("circle", { cx: x(rows.length), cy: y(forecast.forecast), r: 5, fill: "#174e3d", stroke: "#fffefa", "stroke-width": 2 });
  point.append(svgNode("title", {}, `${dateLabel(result.target_date)}: прогноз ${number.format(forecast.forecast)} шт.`));
  svg.append(point);
  svg.append(svgNode("text", { x: x(rows.length), y: y(forecast.forecast) - 12, fill: "#174e3d", "text-anchor": "end", "font-weight": 700 }, number.format(forecast.forecast)));
  $("chart").replaceChildren(svg);
  $("chart").setAttribute("aria-label", `${product}. Прогноз на ${dateLabel(result.target_date)}: ${number.format(forecast.forecast)} штук. Зелёным фоном выделен период проверки.`);
  $("chartHint").textContent = "Последние 56 дней. Зелёный фон — период проверки. Пропуски показаны разрывами; наведите на точку для значения.";
}

function downloadForecast() {
  const result = state.result;
  if (!result) return;
  const cell = (value) => {
    let text = String(value);
    if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  const rows = [["Дата", "Товар", "Прогноз ML, шт.", "Округлённо, шт.", "Неделю назад, шт.", "Среднее 4 недель, шт.", "Данные"]];
  result.forecast.forEach((row) => rows.push([
    result.target_date, row.product, row.forecast, row.rounded, row.lag_7, row.weekday_mean_4,
    result.demo ? "Синтетический пример" : "Загруженный файл",
  ]));
  const content = "\ufeff" + rows.map((row) => row.map(cell).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const link = element("a");
  link.href = url;
  link.download = `прогноз_${result.target_date}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("fileInput").addEventListener("change", (event) => uploadFile(event.target.files[0]));
["dragenter", "dragover"].forEach((type) => $("dropZone").addEventListener(type, (event) => {
  event.preventDefault();
  if (!state.busy) $("dropZone").classList.add("drag");
}));
["dragleave", "drop"].forEach((type) => $("dropZone").addEventListener(type, (event) => {
  event.preventDefault();
  $("dropZone").classList.remove("drag");
}));
$("dropZone").addEventListener("drop", (event) => uploadFile(event.dataTransfer.files[0]));
$("demoButton").addEventListener("click", () => action("Загружаем учебный пример…", async () => {
  resetUpload();
  await acceptUpload(await api("/api/demo", {}));
}));
Object.values(mappings).forEach((select) => select.addEventListener("change", resetPrepared));
$("prepareButton").addEventListener("click", () => action("Проверяем даты, товары и продажи…", prepare));
$("selectAll").addEventListener("click", () => {
  const inputs = [...$("products").querySelectorAll("input")];
  const check = inputs.some((input) => !input.checked);
  inputs.forEach((input) => { input.checked = check; });
  resetResult();
  updateControls();
});
$("missingMode").addEventListener("change", resetResult);
$("trainButton").addEventListener("click", () => action("Обучаем модель и проверяем последние 14 дней. Это может занять несколько минут…", async () => {
  resetResult();
  renderResult(await api("/api/train", { id: state.upload.id, products: selectedProducts(), missing: $("missingMode").value }));
}));
$("downloadButton").addEventListener("click", downloadForecast);
$("chartProduct").addEventListener("change", renderChart);
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderChart, 100);
});
$("fileMode").hidden = !fileMode;
updateControls();
