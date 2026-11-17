# River quality warehouse

Python 3.11+ standard library only. Run from the project root; installation is unnecessary.

```sh
python3.11 -B -m unittest discover -s tests -t . -v
python3.11 -B -m warehouse.workflow verify
python3.11 -B -m warehouse.workflow demo
```

Demo uses its own temporary database and export. To retain them, choose paths within your working directory:

```sh
python3.11 -B -m warehouse.workflow demo --db day.sqlite --export quality.json
```

The simulated river research station receives ordered sampling exports and complete calibration ledgers. Engineers freeze exact input revisions; researchers use qualified details and their matching count; duty staff inspect failed queries. Corrections must preserve previous reports, repeated sampling occurrences must survive, and missing calibration must remain unknown.

## A working day

1. Open Database(path). Missing structures are created; existing sources, bindings, tasks and results remain.
2. Submit ordered sampling rows through SourceService.apply_source(request_id, "sampling", rows). The example includes two identical occurrences of sample 11.
3. Submit a complete calibration revision using dataset "calibration". Same request and same ordered content replay the original receipt; different content is rejected.
4. BindingService.bind_dataset({"samples": sampling_revision_id, "calibrations": calibration_revision_id}) freezes both relations. No binding follows the latest revision.
5. TaskService.create_task(binding_id, query) validates the rule, resolves columns and queues a persistent plan.
6. TaskService.run_task(task_id, batch_size=128) computes ordered details and an independently submitted count query. Initial sample numbers are [11,11,14], count 3.
7. Submit a complete corrected calibration ledger adding B=50, create a new binding and tasks. New details are [11,11,12,14], count 4. Previously queued tasks still use the original revision.
8. Close, reopen and read/export saved results using ResultReader.read_result(task_id, export_path=None). This never recompiles or executes the rule.

All concentrations and limits are integer micrograms/litre. No rounding or implicit conversion occurs. sample_no is a business label, not a unique key. NULL is Python None. Integers are exact, including values beyond 64 bits. Source, plan and result persistence encode integer scalars using hexadecimal text tags; SQLite integer fields hold only internal identifiers and row ordinals.

## Public services and errors

Construct services with the same Database. SourceService, BindingService, QueryPlanner, TaskService and ResultReader are in sources.py, bindings.py, planner.py, tasks.py and exports.py respectively. The workflow module supplies QualityWorkflow and quality_query(count=False) as executable business composition.

* apply_source returns a frozen RevisionReceipt with revision_id, request_id, dataset and row_count. InputError rejects missing/extra fields, booleans in integer fields, floats, numeric strings and request conflicts. No prefix is committed.
* bind_dataset returns DatasetBinding with binding_id and frozen RelationBinding members. BindingError rejects unknown revisions and invalid relation names atomically. Different names may reference the same revision.
* QueryPlanner.compile_query returns (QuerySpec, LogicalPlan). QueryError rejects invalid syntax, types, grouping and references; no task is created.
* create_task returns an integer task_id. get_task returns TaskRecord. run_task returns PublishedResult(task_id, columns, rows). A scalar cardinality error records failed with no rows and raises CardinalityError. Repeating a failed run raises that recorded failure.
* Publication database errors propagate and roll back, leaving queued and no rows. Success publishes all rows and succeeded together. Running a succeeded task returns its stored result.
* read_result returns PublishedResult. ResultUnavailable rejects queued, failed and unknown tasks. Export errors propagate without changing the database. File replacement is atomic.

Database.initialize is repeatable and never seeds or clears business data. Catalog.ensure_schema reuses identical schemas and refuses incompatible names. Supported schemas are sampling(sample_no int, station text, measured_ug_l nullable int) and calibration(station text, limit_ug_l nullable int). All fields must be explicit. Source request identity includes schema, dataset, ordered values and duplicate occurrences, independent of dictionary key order.

## Finite query JSON

A query has from (binding relation name), as (local alias), nonempty ordered select, and optional where, group_by and having. Each select item is {"as":"output_name","expr":EXPRESSION}; output names are unique. group_by is an expression list; supplying it requests grouped rather than global aggregation.

Expressions:

* {"lit":80,"type":"int"}, {"lit":"A","type":"text"}, {"lit":null,"type":"bool"}; literal types are explicit.
* {"col":"station"} reads the current relation. {"col":"station","depth":2} reads the grandparent query row. Optional relation is the alias at the declared depth. Depth is never inferred from names.
* {"op":"le","args":[LEFT,RIGHT]}; comparisons are eq, ne, lt, le, gt, ge and require matching types. and/or take two booleans; not takes one.
* {"agg":"count"} means COUNT(*); {"agg":"count","expr":EXPRESSION} excludes NULL; {"agg":"sum","expr":INTEGER_EXPRESSION} is exact integer SUM.
* {"scalar":QUERY} requires one output column and at most two scalar nesting levels.

No SQL text, joins, DISTINCT, ordering operators, windows or recursive queries are accepted. Aggregate nesting at the same level is illegal; WHERE and GROUP BY prohibit local aggregates. Grouped outputs may use grouping expressions, directly grouped columns, outer references and aggregates. Captures from a grouped parent must refer to directly grouped columns. HAVING requires grouping or a local aggregate.

For example, the maintained quality rule counts same-station calibration rows and compares measurement to their sum only when that count is exactly one. Its complete JSON is returned by quality_query(); this is the same rule used by demo, detail tasks and count tasks.

Comparison with NULL is UNKNOWN. AND/OR/NOT use SQL three-valued logic; filters accept only TRUE. Booleans are evaluated eagerly; a nested cardinality error is not suppressed by another operand.

Projection preserves source occurrence order. Groups preserve first-key occurrence order, with all NULL keys together. Empty global aggregation produces one row, COUNT=0 and SUM=NULL; empty grouped input produces zero rows. HAVING runs afterward and can delete the global row. Scalar conversion sees the final relation: zero rows is NULL, one row is its value, more than one is CardinalityError, even when the rows have equal values. Batch size only changes source batching.

Export JSON contains version, task_id, ordered columns (name/type/nullable), and ordered row arrays. Integer cells are {"integer_hex":"0x..."} or negative hexadecimal tags; text, bool and NULL are native JSON scalars. This avoids decimal digit limits and float coercion. schemas.unpack_value decodes one exported cell. Public Python results contain ordinary exact int values.

## Regression coverage

Eight test modules cover source acceptance/replay/binding (V1,V6), ordered details/NULL/precision and count consistency (V2), two-level scope and plan roundtrip at batch sizes 1/2/17 (V3), empty/grouped/HAVING/scalar shapes (V4), late scalar failure with no published prefix (V5), compile rejection without tasks (V7), SQLite-triggered publication rollback, retry, frozen pending inputs, reopening and read-only export (V8), plus the complete day workflow.

SQLite oracles are separately handwritten SQL on in-memory fixtures; exact values beyond SQLite limits use independent integer expectations. Publication failure uses a real SQLite abort trigger. Disk regressions use temporary directories. Read-only export denies source/catalog reads with SQLite's authorizer. No network or external data is needed.

verify runs complete unittest discovery and propagates failure. Demo performs actual submissions, compilation, execution, publication, export and reopened reads, then prints a POINTWISE_SCENARIO JSON record based on checked results.
