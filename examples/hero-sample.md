# Quarterly report — Q1 2026

A short paragraph with **bold**, *italic*, ~~struck~~, and `inline code`.
This is the sort of mixed-formatting flow that inkmd handles without
choking on edge cases or losing kerning between adjacent styled runs.

> Revenue is up **18% YoY**. The hard part of the next quarter is
> shipping the renderer rewrite without slipping the integration date.

## Numbers

| Region | Q1 2025 | Q1 2026 | Change |
| ------ | ------: | ------: | -----: |
| EMEA   | £142k   | £171k   | +20.4% |
| AMER   | £208k   | £244k   | +17.3% |
| APAC   | £83k    | £98k    | +18.1% |

## Notes

- Renderer test coverage now sits at 94% line, 88% branch.
- The migration from the old XML pipeline is paused until Q2 — see
  the runbook at https://example.com/runbook for the rollback plan.

```python
def quarterly_growth(prev: float, curr: float) -> float:
    return (curr - prev) / prev
```

Footnote: figures audited 2026-04-12. Contact reports@example.com for
the raw spreadsheet.
