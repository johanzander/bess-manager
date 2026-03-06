# Claude Bot Review Configuration

## Default review checklist

Every PR review must cover these aspects, in addition to anything explicitly requested:

- **Architectural principles**: check all principles defined in CLAUDE.md
- **Security**: no credentials in code, no injection vectors (XSS, SQL, command)
- **Tests**: verify tests check behaviour, not implementation details (per CLAUDE.md test guidelines)
