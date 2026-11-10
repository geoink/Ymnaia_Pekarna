# Публикация в geoink/Ymnaia_Pekarna

Репозиторий курсовой — [geoink/Ymnaia_Pekarna](https://github.com/geoink/Ymnaia_Pekarna).

## Обновление опубликованной работы

После редактирования файлов из корня проекта выполните обычный коммит и отправку. Перед добавлением файлов проверьте список изменений командой `git status`.

```bash
git add -- README.md docs notebooks reports/figures MANIFEST.sha256
git commit -m "Update coursework materials"
git push origin main
```

Файлы в отдельном выпуске обновляются следующей командой.

```bash
gh release upload coursework-v2 docs/presentation.pptx docs/presentation.pdf \
  docs/presentation.md docs/requirements_checklist.md \
  --repo geoink/Ymnaia_Pekarna --clobber
gh release edit coursework-v2 --repo geoink/Ymnaia_Pekarna \
  --notes-file docs/release_notes.md
```

Флаг `--clobber` заменяет вложения с такими же именами. Команды ниже описывают первоначальную настройку и отдельный выпуск новой версии.

## Команда для владельца

В Терминале Mac, если GitHub CLI ещё не установлен и есть Homebrew, выполните `brew install gh`. Без Homebrew способы установки перечислены на [cli.github.com](https://cli.github.com). Нужны также Git и Python 3.9+ для публикации; для обучения — Python 3.11+.

Из корня подготовленного проекта:

```bash
gh auth login --hostname github.com --git-protocol https --web --clipboard --scopes workflow &&
gh auth setup-git --hostname github.com &&
python3 scripts/publish_github.py \
  --repo geoink/Ymnaia_Pekarna \
  --public --existing --decorate --with-issues --presentation-release
```

При входе выберите аккаунт **geoink**. Scope `workflow` нужен для загрузки файла GitHub Actions. GitHub CLI попросит подтвердить вход в браузере. Скрипт использует этот вход; токены не передаются в тексте команды и не сохраняются в файлах проекта.

## Что появится после команды

- README с описанием курсовой, навигацией, результатами и графиками.
- Исходники, выполненный ноутбук, презентация, обзор литературы и все сводные отчёты.
- Отдельный выпуск `coursework-v2` с PPTX, PDF, текстом выступления и таблицей требований.
- Описание в блоке About и девять тематических меток: Python, ML, forecasting и другие.
- 18 Issues с постановками для ML-команды, критериями приёмки и ссылками на зависимости.
- Цветные метки приоритетов и поставок R1–R4.
- GitHub Actions для тестов, а также шаблоны новых Issues и Pull Requests.

Флаг `--decorate` берёт описание и topics из [github_metadata.json](github_metadata.json). Он включает Issues; остальные настройки репозитория и его видимость не меняет. Флаг `--public` проверяет, что выбран публичный репозиторий.

Команда инициализирует локальную ветку main, добавляет файлы из `MANIFEST.sha256`, создаёт коммит, подключает пустой origin и выполняет push. Если Git-имя/email не заданы, используются GitHub login и noreply-email **локально в этой папке**. Сырые CSV, модели и окружение исключены из поставки.

## Проверка без публикации

```bash
python3 scripts/publish_github.py \
  --repo geoink/Ymnaia_Pekarna \
  --public --existing --decorate --with-issues --presentation-release --dry-run
```

Этот режим не требует GitHub CLI или сети, показывает план и задачи, но не проверяет права доступа на сервере.

## Повторный запуск и частичная ошибка

Если origin уже совпадает с выбранным репозиторием, выполняется обычный push. Скрипт не использует force-push и не меняет чужой remote. При независимых новых коммитах на GitHub push будет отклонён до ручного согласования историй.

Если файлы загрузились, но обновление About или импорт задач завершились ошибкой, повторите ту же команду после исправления доступа. Существующие Issues, включая закрытые, распознаются по служебной метке и пропускаются. Их текст не перезаписывается. Не запускайте два импорта одновременно.

Отдельный импорт задач:

```bash
python3 scripts/github_tasks.py --repo geoink/Ymnaia_Pekarna --apply
```

Роли записываются в описание; конкретные сотрудники и календарные даты не назначаются. GitHub Project и milestones автоматически не создаются. Фактический статус CI виден во вкладке [Actions](https://github.com/geoink/Ymnaia_Pekarna/actions) после загрузки.

## Если репозиторий перестал быть пустым до первой загрузки

При отсутствии локального origin скрипт остановится, если на GitHub уже есть коммиты. В этом случае клонируйте репозиторий в отдельную папку, скопируйте туда содержимое подготовленного проекта без `.git`, проверьте изменения и сделайте обычный коммит и push. История существующего репозитория сохранится.

Для новых файлов, добавленных самостоятельно после этой поставки, используйте обычные `git add` / `git commit`: скрипт первой публикации добавляет только файлы manifest.

Официальная документация: [gh repo view](https://cli.github.com/manual/gh_repo_view), [gh repo edit](https://cli.github.com/manual/gh_repo_edit), [создание Issue](https://cli.github.com/manual/gh_issue_create).

## Отдельное вложение презентации в GitHub Releases

Готовые файлы находятся в `docs/presentation.pptx` и `docs/presentation.pdf`. README содержит ссылки на скачивание и отдельную страницу презентации.

Чтобы загрузить обновлённый проект и создать выпуск с PPTX, PDF, текстом выступления и таблицей требований, выполните из корня проекта:

```bash
python3 scripts/publish_github.py --repo geoink/Ymnaia_Pekarna \
  --public --existing --decorate --with-issues --presentation-release
```

После успешного push появится выпуск `coursework-v2`. Повторный запуск с тем же коммитом дополняет недостающие вложения, не перезаписывая существующие. Для следующей версии презентации сначала загрузите новый коммит, затем выберите новый тег:

```bash
python3 scripts/release_presentation.py --repo geoink/Ymnaia_Pekarna --tag coursework-v3 --apply
```

Без `--apply` отдельный скрипт показывает локальный план. Он проверяет, что файлы закоммичены и `HEAD` совпадает с `main` на GitHub. Если версия тега указывает на другой коммит, публикация остановится до выбора нового тега.

При входе через `gh auth login --web --clipboard` код активации появляется в Терминале и копируется в буфер. Его нужно вставить на странице Device Activation; этот код не приходит по email. Если браузер запрашивает отдельный код 2FA или подтверждение почты, это другой этап входа в аккаунт.
