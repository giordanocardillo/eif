# Contributing

## Branch rules

`main` is protected. Direct pushes are not allowed — all changes go through pull requests.

## Workflow

```bash
# 1. branch off main
git checkout main && git pull
git checkout -b feature/<short-description>

# 2. make changes, commit
git add <files>
git commit -m "short description of what and why"

# 3. push and open a PR
git push -u origin feature/<short-description>
gh pr create --title "..." --body "..."
```

## Branch naming

| Prefix | Use for |
|---|---|
| `feature/` | New commands, behaviours, or UI changes |
| `fix/` | Bug fixes |
| `docs/` | README, index.html, or in-code doc changes only |
| `chore/` | Dependency bumps, refactors, tooling |

## Commit messages

- Present tense, imperative: `add eif diff command` not `added` or `adds`
- One logical change per commit
- No co-author trailers

## Pull requests

- Target branch: `main`
- Title mirrors the commit message style
- Keep PRs focused — one feature or fix per PR
- PRs from forks are welcome; please open an issue first for large changes

## Releases

Releases are tagged from `main` using semver (`v0.2.0`, `v0.3.0`, …).
Patch releases (`v0.2.1`) for bug fixes, minor releases (`v0.3.0`) for new features, major releases (`v1.0.0`) for breaking changes.
