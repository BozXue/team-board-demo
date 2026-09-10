# Repository instructions for Codex

## Scope

These instructions apply to the whole repository.

## Working agreement

- Read `README.md` and `CONTRIBUTING.md` before changing code.
- Work on a short-lived branch named `codex/<topic>`.
- Do not commit directly to `main`.
- Keep changes focused; do not reformat unrelated files.
- Preserve user changes in a dirty working tree.
- Add or update tests whenever behavior changes.
- Run `make check` before proposing a commit or pull request.
- Use Conventional Commits, for example `feat: add task filtering`.
- Never commit secrets, local environment files, or `data/tasks.json`.

## Architecture

- `src/team_board/board.py`: task model, persistence, and business rules.
- `src/team_board/cli.py`: argument parsing and terminal output.
- `tests/`: standard-library `unittest` test suite.
