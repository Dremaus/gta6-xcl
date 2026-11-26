# {{TITLE}}

**Verdict: {{VERDICT}}**

{{SUMMARY}}

## Host

{{HOST}}

## Runs

{{RUNS_TABLE}}

## Frame budget

{{PHASES}}

## Aggregate (3-run rule)

{{AGGREGATE}}

## Gate at 30 fps

{{GATES}}

## Stability and blockers

{{STABILITY}}

## Method

{{METHOD}}

## Promotion rule

A variant becomes the default only when all of these hold:

- the 30 fps gate is PASS, or the delta against the previous variant is
  repeated and larger than 5% at the same draws and cache state,
- no device removal, no fatal crash, and a valid 3D window,
- VRAM peak stays under 7 800 MB on the 8 GB card,
- the rollback is one env switch or one commit,
- the report carries the exact commands and the measured numbers.
