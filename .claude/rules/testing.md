# Automated Testing Rules

> Claude executes all testing automatically. User sees only results and screenshots.

## When to Test (Auto-Triggers)
| Trigger | Action |
|---------|--------|
| Modified .tsx/.vue/.html/.css file | Visual screenshot verification |
| Created/modified API route or server function | Run endpoint test |
| Bug fix requested | Write regression test FIRST → fix → verify pass |
| Before every git commit | Run full test suite; block if failing |
| After npm/pip install | Run existing tests to verify nothing broke |
| Created new function/module | Write at least 1 unit test (happy path + 1 error) |
| Modified auth or auth logic | Run full auth flow test |
| Modified DB schema or queries | Run CRUD operation tests |

## Unit Test Requirements
- Every new function: minimum 1 test (happy path + 1 error case)
- Every bug fix: regression test BEFORE the fix
- Every utility/helper: edge cases (empty, null, boundary values)
- Coverage target: 80%+

## Integration Tests
For every API endpoint verify:
- Correct status codes (200, 201, 400, 401, 403, 404, 500)
- Correct response shape
- Missing/invalid params → proper errors
- Auth enforced
- Rate limiting (if applicable)

## Pre-Commit Testing
1. Run linter → fix issues automatically
2. Run formatter → apply formatting
3. Run unit tests → ALL must pass
4. Run type checker → no errors
5. Check for console.log/print → remove or warn
6. Check for hardcoded secrets → block if found
7. If ALL pass → commit. If ANY fail → fix first.

## Communication (Non-Technical)
NEVER say:
- "Jest tests passed"
- "Coverage is at 87.3%"
- "The assertion failed on line 42"

ALWAYS say:
- "I tested it — everything works correctly"
- "I verified the login page works — here's a screenshot"
- "Something broke: [plain explanation]. I'm fixing it now."

## Test Framework Detection
- vitest.config.* → Vitest
- jest.config.* → Jest
- pytest.ini / pyproject.toml with pytest → Pytest
- playwright.config.* → Playwright E2E
- No framework + 3+ source files → auto-setup Vitest (Node) or Pytest (Python)
