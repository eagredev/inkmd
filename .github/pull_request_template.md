## What this changes

<!-- One or two sentences. -->

## Why

<!-- Issue this fixes, behaviour this enables, or constraint it lifts. -->

## How to test

<!-- The reviewer needs to be able to verify the change. List steps,
or point at the test that covers it. -->

## Checklist

- [ ] Tests pass locally (`python -m pytest tests/ --ignore=tests/conformance -q`)
- [ ] New behaviour has a test
- [ ] Conformance suites do not regress (or the change improves them
      and `docs/conformance.md` is updated accordingly)
- [ ] Gallery PDFs in `docs/gallery/` still re-render byte-identically
      (or the change deliberately alters output and the new PDFs are
      committed)
- [ ] No new runtime dependencies
