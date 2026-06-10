# Wide tables and page breaks

New in 0.5: a table too wide for the page fits losslessly, and a
document can force a page break with the standard CSS break div.

## A table that shrinks and wraps

Natural column widths overflow the page, but every column can reach
a readable width, so the table renders on one strip with wrapped
cell text and nothing lost.

| Region name | Engineer on call | Deployment status | Incident summary | Maintenance window |
| --- | --- | --- | --- | --- |
| region-a primary | engineer 1, platform team | rollout 1 complete in all zones | 0 incidents, none breached budget | weekend 1 of next month |
| region-b primary | engineer 2, platform team | rollout 2 complete in all zones | 1 incidents, none breached budget | weekend 2 of next month |
| region-c primary | engineer 3, platform team | rollout 3 complete in all zones | 2 incidents, none breached budget | weekend 3 of next month |
| region-d primary | engineer 4, platform team | rollout 4 complete in all zones | 3 incidents, none breached budget | weekend 4 of next month |

<div style="page-break-after: always"></div>

## A table that splits into panels

Twenty-four columns cannot fit a letter page even at minimum widths,
so the table splits into column panels. Each panel repeats the first
column as the key and is marked as continued.

| service | wk01 | wk02 | wk03 | wk04 | wk05 | wk06 | wk07 | wk08 | wk09 | wk10 | wk11 | wk12 | wk13 | wk14 | wk15 | wk16 | wk17 | wk18 | wk19 | wk20 | wk21 | wk22 | wk23 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| svc-00 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 |
| svc-01 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 |
| svc-02 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 |
| svc-03 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 |
| svc-04 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 |
| svc-05 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 |
| svc-06 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 |
| svc-07 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 | 99.1 | 99.2 | 99.3 | 99.4 | 99.5 | 99.6 | 99.7 | 99.8 | 99.9 | 99.0 |

<div style="page-break-after: always"></div>

## After the second break

This heading started a fresh page because of the break div above.
The div itself renders as nothing on GitHub, so a document carrying
it stays portable between web view and PDF.
