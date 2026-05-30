# Contributing to inkmd

Bug reports, fixes, and small features are welcome. Larger or
ambiguous work is best discussed in an issue first.

## Before opening a pull request

- Tests pass: `python -m pytest tests/ --ignore=tests/conformance -q`.
- New behaviour has a test covering it (unit test in `tests/`).
- For parser or renderer changes, the conformance suites still pass
  the same set of tests they did before (or your PR explicitly
  improves the numbers and updates `docs/conformance.md`):
  ```sh
  python tests/conformance/run_commonmark.py
  python tests/conformance/run_gfm.py --extensions-only
  ```
- Output is still deterministic: the gallery PDFs in `docs/gallery/`
  re-render byte-identically. The session-handoff snippet at the
  bottom of `docs/internals.md` has the re-render command.

## Project shape

- **Pure-Python, stdlib-only.** No runtime dependencies. Test-time
  `pytest` is the only addition.
- **Four layers** (`parser` -> `render` -> `layout` -> `pdf`), each
  importing strictly below itself. See `docs/internals.md` for the
  rationale.
- **Frozen-dataclass AST.** Nodes are immutable; transformations
  produce new nodes.
- **Python 3.9+** is the supported floor. CI runs 3.9 through 3.13.

## Style

- Match the surrounding code. No re-formatter or linter is wired
  into CI; the existing code is consistent enough that grepping
  for a nearby pattern is the fastest style guide.
- Keep new modules small and single-responsibility, like the
  existing ones.

## Filing bugs

- A minimal markdown input that reproduces the bug.
- What you expected and what you got.
- The output of `inkmd --version` (or commit SHA if running from a
  checkout).

## Filing feature requests

The roadmap in `README.md` and `docs/conformance.md` lists what is
already planned for v0.3 and v0.4. If your idea is already on the
list, a comment on an existing issue (or a PR implementing it) is
more useful than a duplicate request.

## Licence

By contributing you agree that your contributions are MIT-licensed
under the same terms as the rest of the project (see `LICENSE`).
