"""Benchmark how a composite SQLite index changes trade-audit queries.

The project uses only Python's standard library. It creates deterministic
synthetic trade data, records SQLite query plans and VDBE opcodes, and compares
median runtimes before and after adding an index on (ticker, execution_date).
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence


TICKERS = (
    "AAPL", "AMD", "AMZN", "BAC", "BRK.B", "C", "GOOG", "JPM", "META",
    "MSFT", "NFLX", "NVDA", "QQQ", "SPY", "TSLA", "UBER", "V", "WMT",
    "XOM", "ZM",
)
SIDES = ("BUY", "SELL")
QUANTITIES = (10, 25, 50, 100, 200, 500, 1_000)
INDEX_NAME = "idx_trades_ticker_date"


@dataclass(frozen=True)
class QuerySpec:
    """A named, parameterized audit query."""

    name: str
    sql: str
    params: tuple[Any, ...]


@dataclass(frozen=True)
class TimingSummary:
    """Timing statistics for one query and one index state."""

    median_seconds: float
    minimum_seconds: float
    maximum_seconds: float
    returned_rows: int
    measurements: tuple[float, ...]


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open SQLite with settings appropriate for a reproducible local demo."""

    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the trade table."""

    connection.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            execution_date TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
            price REAL NOT NULL CHECK (price > 0),
            quantity INTEGER NOT NULL CHECK (quantity > 0)
        )
        """
    )
    connection.commit()


def _trade_rows(record_count: int, seed: int) -> Iterable[tuple[Any, ...]]:
    rng = random.Random(seed)
    first_day = date(2025, 1, 1)
    for trade_id in range(1, record_count + 1):
        execution_date = first_day + timedelta(days=rng.randrange(365))
        yield (
            trade_id,
            rng.choice(TICKERS),
            execution_date.isoformat(),
            rng.choice(SIDES),
            round(rng.uniform(10.0, 750.0), 2),
            rng.choice(QUANTITIES),
        )


def populate_database(
    connection: sqlite3.Connection,
    record_count: int,
    seed: int = 42,
    batch_size: int = 10_000,
) -> None:
    """Insert deterministic synthetic trades in bounded-memory batches."""

    if record_count < 1:
        raise ValueError("record_count must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    insert_sql = "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?)"
    batch: list[tuple[Any, ...]] = []
    for row in _trade_rows(record_count, seed):
        batch.append(row)
        if len(batch) == batch_size:
            connection.executemany(insert_sql, batch)
            batch.clear()
    if batch:
        connection.executemany(insert_sql, batch)
    connection.commit()


def create_composite_index(connection: sqlite3.Connection) -> None:
    """Index the leading filters and sort key used by the audit queries."""

    connection.execute(
        f"CREATE INDEX {INDEX_NAME} ON trades (ticker, execution_date)"
    )
    connection.commit()


def build_queries(
    ticker: str,
    point_date: str,
    start_date: str,
    end_date: str,
) -> tuple[QuerySpec, ...]:
    """Build the three parameterized workloads used in the benchmark."""

    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker cannot be empty")
    parsed_point = date.fromisoformat(point_date)
    parsed_start = date.fromisoformat(start_date)
    parsed_end = date.fromisoformat(end_date)
    if parsed_start > parsed_end:
        raise ValueError("start_date must be on or before end_date")

    columns = "id, ticker, execution_date, side, price, quantity"
    return (
        QuerySpec(
            "point_lookup",
            f"SELECT {columns} FROM trades "
            "WHERE ticker = ? AND execution_date = ?",
            (normalized_ticker, parsed_point.isoformat()),
        ),
        QuerySpec(
            "date_range",
            f"SELECT {columns} FROM trades "
            "WHERE ticker = ? AND execution_date BETWEEN ? AND ?",
            (
                normalized_ticker,
                parsed_start.isoformat(),
                parsed_end.isoformat(),
            ),
        ),
        QuerySpec(
            "recent_top_5",
            f"SELECT {columns} FROM trades WHERE ticker = ? "
            "ORDER BY execution_date DESC, id DESC LIMIT 5",
            (normalized_ticker,),
        ),
    )


def explain_query_plan(
    connection: sqlite3.Connection, query: QuerySpec
) -> list[str]:
    """Return SQLite's high-level plan descriptions."""

    rows = connection.execute(
        "EXPLAIN QUERY PLAN " + query.sql, query.params
    ).fetchall()
    return [str(row[3]) for row in rows]


def explain_opcodes(
    connection: sqlite3.Connection, query: QuerySpec
) -> list[str]:
    """Return the ordered VDBE opcode names for a query."""

    rows = connection.execute("EXPLAIN " + query.sql, query.params).fetchall()
    return [str(row[1]) for row in rows]


def execute_query(
    connection: sqlite3.Connection, query: QuerySpec
) -> list[tuple[Any, ...]]:
    """Execute one parameterized query and materialize its result."""

    return connection.execute(query.sql, query.params).fetchall()


def benchmark_query(
    connection: sqlite3.Connection,
    query: QuerySpec,
    iterations: int,
    repeats: int,
    warmups: int,
) -> TimingSummary:
    """Measure repeated query execution and report the median repeat time."""

    if iterations < 1 or repeats < 1 or warmups < 0:
        raise ValueError("iterations/repeats must be positive and warmups nonnegative")

    for _ in range(warmups):
        execute_query(connection, query)

    measurements: list[float] = []
    returned_rows: int | None = None
    for _ in range(repeats):
        started = time.perf_counter()
        final_result: list[tuple[Any, ...]] = []
        for _ in range(iterations):
            final_result = execute_query(connection, query)
        elapsed = time.perf_counter() - started
        if returned_rows is None:
            returned_rows = len(final_result)
        elif returned_rows != len(final_result):
            raise RuntimeError("query returned an inconsistent row count")
        measurements.append(elapsed)

    return TimingSummary(
        median_seconds=statistics.median(measurements),
        minimum_seconds=min(measurements),
        maximum_seconds=max(measurements),
        returned_rows=returned_rows or 0,
        measurements=tuple(measurements),
    )


def _benchmark_phase(
    connection: sqlite3.Connection,
    queries: Sequence[QuerySpec],
    iterations: int,
    repeats: int,
    warmups: int,
) -> dict[str, dict[str, Any]]:
    phase: dict[str, dict[str, Any]] = {}
    for query in queries:
        timing = benchmark_query(
            connection, query, iterations=iterations, repeats=repeats, warmups=warmups
        )
        phase[query.name] = {
            "timing": asdict(timing),
            "query_plan": explain_query_plan(connection, query),
            "opcodes": explain_opcodes(connection, query),
        }
    return phase


def run_benchmark(
    connection: sqlite3.Connection,
    queries: Sequence[QuerySpec],
    iterations: int = 50,
    repeats: int = 5,
    warmups: int = 3,
) -> dict[str, Any]:
    """Benchmark the same workloads before and after index creation."""

    expected_results = {query.name: execute_query(connection, query) for query in queries}
    unindexed = _benchmark_phase(connection, queries, iterations, repeats, warmups)
    create_composite_index(connection)
    indexed = _benchmark_phase(connection, queries, iterations, repeats, warmups)

    comparisons: dict[str, dict[str, float]] = {}
    for query in queries:
        actual = execute_query(connection, query)
        # SQL does not guarantee row order without ORDER BY. Compare the same
        # result set by primary key while preserving the top-K query's own order.
        if sorted(actual) != sorted(expected_results[query.name]):
            raise RuntimeError(f"index changed results for {query.name}")
        before = unindexed[query.name]["timing"]["median_seconds"]
        after = indexed[query.name]["timing"]["median_seconds"]
        comparisons[query.name] = {
            "speedup": before / after if after else float("inf"),
            "runtime_reduction_percent": (1.0 - after / before) * 100.0,
        }

    return {
        "benchmark": {
            "iterations_per_repeat": iterations,
            "repeats": repeats,
            "warmups_per_phase": warmups,
            "timing_statistic": "median total seconds per repeat",
        },
        "unindexed": unindexed,
        "indexed": indexed,
        "comparison": comparisons,
    }


def print_summary(results: dict[str, Any]) -> None:
    """Print a compact human-readable benchmark table and query plans."""

    print("\nSQLite Trade Audit Benchmark")
    print("=" * 88)
    print(f"{'Query':<18}{'Rows':>8}{'Before (s)':>16}{'After (s)':>16}{'Speedup':>14}{'Reduction':>16}")
    print("-" * 88)
    for name, comparison in results["comparison"].items():
        before = results["unindexed"][name]["timing"]
        after = results["indexed"][name]["timing"]
        print(
            f"{name:<18}{before['returned_rows']:>8,}"
            f"{before['median_seconds']:>16.6f}{after['median_seconds']:>16.6f}"
            f"{comparison['speedup']:>13.2f}x"
            f"{comparison['runtime_reduction_percent']:>15.2f}%"
        )

    print("\nPlan changes")
    print("-" * 88)
    for name in results["comparison"]:
        before_plan = " | ".join(results["unindexed"][name]["query_plan"])
        after_plan = " | ".join(results["indexed"][name]["query_plan"])
        print(f"{name}:\n  before: {before_plan}\n  after:  {after_plan}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark SQLite trade-audit queries before and after indexing."
    )
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--point-date", default="2025-06-15")
    parser.add_argument("--start-date", default="2025-06-01")
    parser.add_argument("--end-date", default="2025-06-30")
    parser.add_argument(
        "--database",
        type=Path,
        help="Optional database path. A temporary database is used by default.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of an existing --database file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/benchmark.json"),
        help="JSON results path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.records < 1 or args.iterations < 1 or args.repeats < 1 or args.warmups < 0:
        raise SystemExit("records/iterations/repeats must be positive; warmups nonnegative")

    temporary_path: Path | None = None
    if args.database:
        database_path = args.database.resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists() and not args.overwrite:
            raise SystemExit(f"database already exists: {database_path}; use --overwrite")
        if database_path.exists():
            database_path.unlink()
    else:
        handle = tempfile.NamedTemporaryFile(prefix="trade_audit_", suffix=".db", delete=False)
        handle.close()
        database_path = Path(handle.name)
        database_path.unlink()
        temporary_path = database_path

    try:
        connection = connect_database(database_path)
        try:
            print(f"Creating {args.records:,} deterministic synthetic trades...")
            create_schema(connection)
            populate_database(connection, args.records, seed=args.seed)
            queries = build_queries(
                args.ticker, args.point_date, args.start_date, args.end_date
            )
            results = run_benchmark(
                connection,
                queries,
                iterations=args.iterations,
                repeats=args.repeats,
                warmups=args.warmups,
            )
        finally:
            connection.close()

        results["dataset"] = {
            "records": args.records,
            "seed": args.seed,
            "ticker": args.ticker.strip().upper(),
            "point_date": args.point_date,
            "range": [args.start_date, args.end_date],
            "database": (
                str(database_path)
                if args.database
                else "temporary file (deleted after benchmark)"
            ),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print_summary(results)
        print(f"\nSaved full plans, opcodes, and timings to {args.output}")
        return 0
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
