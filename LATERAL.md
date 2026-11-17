# Ordered calibration candidate expansion

The existing V1 engine, public Python services, data schemas, errors, persistence and original regression suite are described in README.md. This extension supplies a related relation as input to the same fixed task. It does not change scalar cardinality rules.

## Public query contract

Continue using TaskService.create_task(binding_id, query), run_task(task_id, batch_size=128), QueryPlanner.compile_query and ResultReader.read_result. No new service endpoint is required.

A top-level query may additionally contain exactly this optional member:

```json
"lateral": {"as": "r", "mode": "left", "query": RIGHT_QUERY}
```

The member must be an object with exactly as, mode and query. as obeys the existing alias naming rule and differs from the top-level as; mode is inner or left. RIGHT_QUERY uses the existing finite query JSON, including projection, WHERE, grouping, aggregates, HAVING and scalar subqueries. The top-level query containing lateral may not contain group_by or having; ordinary V1 global aggregation remains allowed. No query below the root may contain lateral. The maximum query nesting level remains two below the root: entering either a scalar query or RIGHT_QUERY increases the level by one.

The top-level from/as still identifies the left source. The right alias exposes the ordered select output names and types of RIGHT_QUERY, not its original source columns. An unselected right source column is not visible through that alias. All relations used anywhere come from the task's same fixed binding.

Column references retain col, optional depth (default 0) and optional relation. relation means an alias at exactly the declared depth; it never searches other depths. Within RIGHT_QUERY, depth=0 refers to its own from/as and depth=1 refers only to the current original left source row. Its own output alias is not a parent input. A scalar inside RIGHT_QUERY sees its immediate right source at depth=1 and that original left source at depth=2.

After expansion, the top-level input is one query scope containing the left source and the right output. At that scope, relation selects the appropriate left/right alias. An unqualified column is legal only if exactly one side has that name; absent or ambiguous names raise QueryError. These same rules apply when a top-level scalar captures the combined scope at depth=1, or its nested scalar captures it at depth=2. Combining two inputs must not create an extra lexical query level. Local aliases in deeper queries may shadow outer aliases; explicit depth still chooses the scope. Different aliases or even two sides reading the same bound source do not make their column slots interchangeable.

Invalid syntax, aliases, references, types, aggregate positions, nesting or unsupported shapes raise QueryError during create_task, before a task is saved. All existing V1 aggregate checks still apply.

## Rows, NULL and static outputs

Evaluate RIGHT_QUERY independently for every left source occurrence, including identical repeated rows. Consume its final ordered relation after its WHERE, grouping, aggregation, HAVING and projection. Emit rows in left occurrence order and then right final row order. Duplicate rows and occurrences survive. No order is inferred from values or output aliases.

inner emits no row for an empty right final relation. left emits exactly one combined row with every right output cell NULL for an empty right final relation. A real right row whose cells happen to be NULL is still a row. An empty global COUNT result is one row containing 0; an empty grouped relation is zero rows; HAVING can remove the global aggregate row. Null extension is determined only after this final relation is known.

Top-level WHERE runs after expansion/null extension, accepts only TRUE, and uses the existing three-valued and eager expression semantics. Top-level projection or global aggregation then uses the combined input. Left input column types and nullability are unchanged. In left mode every exposed right column is nullable, including originally non-null outputs such as COUNT; inner preserves original right output nullability. This widening applies only to the combined input and derived top-level expressions; it must not modify RIGHT_QUERY's internal type, grouping or aggregate semantics.

The compiled plan and queued task must freeze the input ownership, output types, right query, mode and capture meanings. encode_plan/decode_plan must roundtrip the new plan. Queued tasks created before a source correction, changed caller JSON, or database close/reopen keep their original binding and expansion. Keep existing persisted V1 plans, tasks and results readable. Original scalar subqueries still return NULL for zero rows, their single value for one row, and raise CardinalityError for multiple final rows, including equal values.

Keep the existing failure boundary: a late scalar error makes the whole task failed with no result prefix; a publication database exception propagates, leaves queued with no result rows, and permits retry. A saved successful result is read/exported without re-executing the query. Exact integers, source revisions, request replay and original interfaces remain unchanged.

## Complete example and business expectations

lateral_examples.py supplies ordinary input rows, complete query JSON constructors and hand-calculated outputs. Its fixtures command prints the base input/query/output without using the new capability. SAMPLES contains two identical A occurrences, one B and one C; CALIBRATIONS contains ordered A=100, A=120 and C=NULL. candidates() projects sample_no, left_station, right_station and limit. The left-mode result is:

```text
[11,"A","A",100]
[11,"A","A",120]
[11,"A","A",100]
[11,"A","A",120]
[12,"B",NULL,NULL]
[13,"C","C",NULL]
```

inner omits only B. A top-level limit>110 filter leaves the two A=120 rows. With a single B sample and empty calibration, right global COUNT, grouped COUNT, and global COUNT with HAVING COUNT>0 yield left outputs [0], [NULL], [NULL] respectively; inner yields [0], no rows, no rows.

The supplied checks also exercise same-source left/right IDs 11 and 15 (all four ordered pairs), captures from both combined sides, a scalar inside the right query capturing its source and the original left row, invalid ambiguous and unavailable references, static nullable outputs, unchanged scalar failures, publication interruption, fixed queued plans and reopened saved results. They are examples of the public rules, not a substitute for complete implementation. Do not weaken or remove the original tests.

## Delivery and execution

Implement the linked planning and execution changes and explain briefly how input identity, lexical depth, nullable right outputs and occurrence order are maintained across their interface. Nested-loop evaluation, full recomputation and materialized right results are allowed. No optimizer, nested lateral, new ordering/window/DISTINCT operators, incremental refresh, concurrent execution or object reclamation is required.

The original .pointwise-runtime.json is supplied unchanged. Retain version 1, kind cli and setup as a list of argv arrays. Connect its verify argv to joint original-and-extension business verification, and its demo argv to the candidate expansion/correction/reopen demonstration. The supplied complete entry points are:

```sh
python3.11 -B lateral_examples.py fixtures
python3.11 -B -m unittest discover -s tests -t . -v
python3.11 -B lateral_examples.py verify
python3.11 -B lateral_examples.py demo
```

verify must propagate nonzero on any failed check. demo must compute and check actual old/new results and print them, including the formerly unmatched B after adding B=50, while the old queued task keeps its unmatched B. The existing V1 verify/demo entry points remain usable. No implementation of lateral is included in these added materials.
