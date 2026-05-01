# Project: mymed

## Overview
Project created with /setup. Idea and tech stack will be defined by the user.

## How Claude Should Work With the User
- User writes prompts, not code — explain everything in plain language
- Before making changes: say what you'll change and why
- After changes: explain how to verify (which URL, what to click)
- If prompt is vague: ask clarifying questions BEFORE writing code
- Change ONLY what was asked — never refactor or "improve" uninstructed code
- If changing 4+ files: list them and get confirmation first
- Never show raw error messages without plain-language explanation
- Speak in Georgian unless user switches to English

## Data Safety
- Auto-checkpoint before any multi-file change
- Never delete files without asking
- If user says "undo" — use git to restore

## Security Rules
- Never put secrets in code — use environment variables
- Validate all user inputs
- Use parameterized queries
(detailed rules in .claude/rules/security.md)

## Testing (mandatory — automatic)
- After every function: run tests
- After every UI change: Playwright screenshot + show user
- Before commit: tests MUST pass
- New endpoint/page: minimum 1 test
(detailed rules in .claude/rules/testing.md, ui-verification.md)

## Code Quality
- Linter must pass (will be configured when tech stack is chosen)
- Formatter for consistency
- Conventional commits: feat:, fix:, docs:, test:, refactor:, chore:

## Memory & Context
- End of session: save important decisions
- Start of session: read previous context
- Architectural decisions: save to docs/decisions/
(detailed rules in .claude/rules/memory.md)

## Ежемесячная задача: Генерация медкарт реабилитации

**Что делает:** Заполняет Excel-карты пациентов по шаблонам (МКБ-код → шаблон), 41 файл за ~30 сек.

**Каждый месяц:**
1. Получить новый файл списка пациентов `MM ДД.ММ T.xlsx`
2. Открыть `c:\Users\user\Desktop\generate_med_cards.py`
3. В секции НАСТРОЙКИ (строка ~14) изменить путь к файлу:
   ```
   PATIENT_LIST = r'c:\Users\user\Desktop\Moimed shablon\MM 05.26 T.xlsx'
   ```
4. Запустить: `py -3 c:\Users\user\Desktop\generate_med_cards.py`
5. Результат: `c:\Users\user\Desktop\Готовые карты\`

**Структура данных (список пациентов):**
- Каждый пациент = 2 строки в файле:
  - Строка 1 (АПП1): первичный приём специалиста → даты идут в листы АПП1/АПП2
  - Строка 2 (rehab): реабилитация (в примечаниях код 2259601/2019601/1099601/2409601)
- Колонка МЭЭ (8) = ФИО врача, используется для листов АПП1/АПП2

**Шаблоны в папке `Moimed shablon\`:**
- `G24.8.xlsx` → G24.8, G90.8, G93.4 (неврология, дети)
- `М54.2.xlsx` → M54.2, M53.x, M54.x, I10, I11.9, I67.8, I69.3 (взрослые)
- `М42.1.xlsx` → M42.0, M42.1, M23.8 (опорно-двигательный)
- `М 50.1.xlsx` → M50.1 (грыжа диска)
- `G96.8.xlsx` → G96.8

**Если нужно добавить новый МКБ-код:** Открыть скрипт, найти `TEMPLATE_MAP` и добавить строку.

**Скрипт:** `c:\Users\user\Desktop\generate_med_cards.py`
