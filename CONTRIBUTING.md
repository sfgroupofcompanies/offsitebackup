# Contributing to Offsite Backup

This document provides guidelines for contributing to the Offsite Backup Frappe app.

## Prerequisites

- Python 3.10+
- Node.js 18+
- MariaDB 10.6+
- Redis
- Frappe Bench (version-15)

## Development Setup

```bash
# in your bench
cd ~/frappe-bench
bench get-app offsitebackup <repo-url>
bench --site your-site.local install-app offsitebackup

# install pre-commit hooks
cd apps/offsitebackup
pre-commit install
```

## Making Changes

- Create a feature branch off `version-15-beta`.
- Keep changes focused and add tests where applicable.
- Run linters before pushing:

```bash
pre-commit run --all-files
```

## Commit Guidelines

We use Conventional Commits:

```
<type>(<scope>): <description>
```

Allowed types include: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `patch`.

## Pull Request Checklist

- Code follows project style
- `pre-commit` passes
- Tests pass (when applicable)
- Documentation updated (if needed)
