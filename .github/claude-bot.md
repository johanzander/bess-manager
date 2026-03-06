# Claude Bot Review Configuration

## Default review checklist

Every PR review must cover these aspects, in addition to anything explicitly requested:

- **Architectural principles**: check all principles defined in CLAUDE.md
- **Security**: no credentials in code, no injection vectors (XSS, SQL, command)
- **Tests**: verify tests check behaviour, not implementation details (per CLAUDE.md test guidelines)
- **Fitness of approach**: for every substantive change, ask two questions:
  (1) Is this the best available solution, or merely better than what it replaced?
  (2) Does it hold for all valid inputs and configurations, not just the case that triggered it?
  Name specific failure modes or better alternatives if they exist.
