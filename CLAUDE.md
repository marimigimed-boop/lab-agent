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
