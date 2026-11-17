# Ordered calibration candidate expansion — implementation handoff

This note explains how the V1 engine was extended per LATERAL.md. Public services,
schemas, errors, persistence tables and the original tests are unchanged.

## Representation interface (planning → persistence → execution)

A top-level query may carry `lateral: {as, mode, query}`. Compilation produces a
`LogicalPlan` whose new optional member is a `LateralPlan`:

| field        | meaning                                                              |
|--------------|----------------------------------------------------------------------|
| `alias`      | right alias (`r`)                                                    |
| `mode`       | `inner` or `left`                                                    |
| `outputs`    | exposed right columns with combined-input nullability (left ⇒ all nullable) |
| `column_ids` | right frame slots, unique per top-level scope                         |
| `plan`       | nested right `LogicalPlan`, original types and semantics preserved    |

**Input identity.** The top-level `scope_id` owns a combined `Scope` with two
sides: the original left relation and the right output alias. Right slots are
named `<scope_id>:<alias>:<index>:<name>`, so they never collide with left
identities even when both sides read the same bound source
(`test_same_source_identities`, `test_plan_freezes_both_sides`). Two sides reading
one revision still own distinct slots; the left `column_ids` keep their source
identity unchanged.

**Lexical depth.** `Scopes.push` adds exactly one scope per query level. Entering
RIGHT_QUERY nudges `level` by 1 but pushes a *single-side* view of the left scope
for it, so inside RIGHT_QUERY: depth 0 = its own source, depth 1 = the original
left row, and a scalar's immediate right source is depth 1 with the left row at
depth 2. Combining the inputs at the top adds **no** extra level — the combined
scope replaces the single-side left scope in the stack, so an unqualified name
resolves against both sides, legal only when unique; ambiguous names raise
`QueryError` (`test_unqualified_rules_after_expansion`, `test_depth_and_shadowing`).
Right-output names are the projected select names only; unselected source
columns are invisible through the alias.

**Nullable right outputs.** Nullability widening happens only when building the
combined side (`exposed`) and flows into top-level expressions; `lateral.plan.outputs`
keeps the right query's original nullability. So a left-mode `COUNT` is exposed
nullable while the right internal aggregate stays non-null
(`test_nullable_widening_does_not_touch_right_semantics`,
`test_grouped_right_keeps_internal_types`).

**Occurrence order.** `QueryExecutor.expand` evaluates the right plan once per left
occurrence (nested loop, full recompute) and yields combined frames left-order
then right-final-order, preserving duplicates. Null extension is applied only
after the final right relation is known, so a real all-NULL row is still a row,
an empty global aggregate is one `0` row, an empty grouped relation is zero rows,
and inner simply emits nothing. Top-level WHERE runs after expansion and accepts
only TRUE.

**Persistence.** `encode_plan`/`decode_plan` recurse through the nested right plan.
`lateral: null` members are stripped recursively on encode, so persisted V1 plan
bytes (including nested scalar subplans) are byte-identical to the pre-extension
encoder (verified against a checkout of the original commit); old plans, tasks
and results stay readable.

## Execution wiring

* `planner.py` — `compile_lateral` builds the right plan at `level+1` against the
  left-only parent, then the combined scope and `LateralPlan`.
* `scopes.py` — multi-sided `Scope`/`ScopeSide`; `resolve_column` enforces
  depth/alias and unique unqualified names.
* `query_validation.py` — `lateral` accepted only at `level == 0`; forbids
  `group_by`/`having` beside it; exactly `as`/`mode`/`query`; alias differs from
  top-level `as`; mode `inner`/`left`.
* `executor.py` — `expand` performs the per-left nested loop and NULL extension.
* `plan_codec.py` — roundtrips the nested plan without changing V1 bytes.
* No task row is written until compilation succeeds; existing failure/publication
  boundaries are untouched.

## Running

`.pointwise-runtime.json` (version 1, kind cli, setup `[]`) now points both
commands at the joint business verification and the candidate demo:

```sh
python3.11 -B lateral_examples.py verify   # original 16 + supplied 7 + added 7 = 30
python3.11 -B lateral_examples.py demo     # old queued B unmatched; new B=50 matched
```

`python3.11 -B -m warehouse.workflow verify|demo` still runs the original V1
suite/demo. The demo output shows the frozen old task keeping its unmatched B
while the corrected-calibration task gains `[12, "B", "B", 50]`.
