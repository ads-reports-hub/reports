# ads-reports-hub/reports

Автоматическая ежемесячная генерация отчётов по рекламе Meta Ads для клиентов
Лизы (@elzabutirina). Полное описание архитектуры и разовых ручных шагов
настройки — см. итоговую инструкцию, переданную Максиму отдельно (и план в
`/Users/maksimbaranov/.claude/plans/jazzy-orbiting-rocket.md` в проекте
"Liza Baturina").

Коротко:
- `engine/` — вся логика: чтение таблицы клиентов, тянущий метрики из Meta,
  генерация текстов через Anthropic API, рендер шаблона.
- `templates/` — Jinja2-шаблон страницы отчёта + статичные строки интерфейса.
- `docs/` — то, что публикует GitHub Pages (см. `docs/README.md`).
- `.github/workflows/monthly-report.yml` — расписание (1-е число месяца) +
  ручной запуск (`workflow_dispatch`) для тестов.
- `apps-script/Code.gs` — эталонная копия скрипта, который должен быть
  вручную вставлен в саму гугл-таблицу (Extensions -> Apps Script), чтобы
  дописывать ссылки обратно в таблицу.

Требуемые секреты репозитория (Settings -> Secrets and variables -> Actions):
`ANTHROPIC_API_KEY`, `SHEET_WEBAPP_URL`, `SHEET_SHARED_SECRET`.
