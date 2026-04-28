# Code Quality Rules

## Linting & Formatting
- Linter must pass with zero errors before every commit
- Auto-format on save (prettier/black/gofmt depending on stack)
- Max line length: 88 chars (Python black default) / 100 chars (TS)

## Git Workflow
- Branches: main → develop → feature/xxx or fix/xxx
- Never commit directly to main
- Feature branch naming: feature/short-description
- Fix branch naming: fix/short-description

## Commit Format (Conventional Commits)
```
type: short description (max 72 chars)

[optional body — what and why]
```
Types: feat, fix, refactor, docs, test, chore, perf, ci

Examples:
- feat: add appointment booking form
- fix: prevent duplicate patient records
- test: add integration tests for auth flow

## Pre-Commit Checklist
- [ ] Linter passes (zero errors)
- [ ] Formatter applied
- [ ] No console.log / print statements in production code
- [ ] No hardcoded secrets
- [ ] Tests pass (if applicable)

## Code Review (Self-Review Before Commit)
- Re-read every changed file
- Check for security issues
- Check for performance issues
- Verify no unintended changes

## File Organization
- One concept per file (one component, one service, one model)
- Max 400 lines per file; extract when larger
- Functions under 50 lines
- Max 4 levels of nesting

## Naming Conventions
- Variables/functions: describe WHAT, not HOW
- Booleans: isActive, hasPermission, canEdit
- Collections: plural nouns (users, appointments)
- Functions: verb + noun (createUser, validateEmail)
