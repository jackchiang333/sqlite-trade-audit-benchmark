# Benchmarking Methodology

## Workload

The program generates synthetic trades with uniformly sampled tickers and dates. It then benchmarks the same parameterized SQL before and after creating:

```sql
CREATE INDEX idx_trades_ticker_date
ON trades (ticker, execution_date);
```

The index matches the leading equality filter (`ticker`) and the secondary date filter or ordering requirement.

## Timing design

- `time.perf_counter()` provides a high-resolution monotonic clock.
- Each phase includes configurable warm-up executions.
- Each reported value is the median of multiple repeats.
- Every repeat executes the query multiple times and fully materializes the result.
- Raw repeat times are retained in the JSON output.
- Correctness checks confirm that indexed and unindexed results are identical.

## Complexity interpretation

An index lookup is not simply `O(log N)` when a query returns multiple records. A more accurate expression is `O(log N + K)`, where `K` is the number of matching index entries and returned rows. Large range queries may therefore improve less than highly selective point or top-K queries.

## Important limitations

1. Unindexed and indexed phases run sequentially on one machine, so cache state cannot be perfectly identical.
2. SQLite performance depends on its version, filesystem, storage, memory, and compile-time settings.
3. The benchmark measures a read-heavy, single-process workload. It does not simulate concurrent writers or networked database access.
4. Synthetic data do not reproduce every clustering, skew, or burst pattern found in real execution records.
5. The secondary index is not covering because the queries return all trade columns; SQLite may still perform table lookups after finding index entries.

These constraints are why the project reports plans, opcodes, repeat-level timings, and returned row counts rather than presenting one runtime as a general performance guarantee.
