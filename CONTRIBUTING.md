# Contributing

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone <your-fork-url>`
3. Create a feature branch: `git checkout -b feature/your-feature`
4. Make your changes
5. Run tests to verify everything works
6. Commit using conventional format (see below)
7. Push to your fork and open a Pull Request

## Branch Naming

- `feature/short-description` — new features
- `fix/short-description` — bug fixes
- `docs/short-description` — documentation only
- `refactor/short-description` — code changes without behavior change

## Commit Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
type: short description (max 72 chars)
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`

Examples:
- `feat: add appointment booking endpoint`
- `fix: resolve duplicate patient creation`
- `test: add unit tests for auth service`

## Code Standards

- Follow existing code style
- Run linter before committing (zero errors required)
- Write tests for new features
- Update documentation if API changes

## Pull Request Guidelines

- Fill in the PR template completely
- Keep PRs focused — one feature or fix per PR
- Add screenshots for UI changes
- Ensure all CI checks pass before requesting review

## Code of Conduct

Be respectful and constructive. We're all here to build something useful.
