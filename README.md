# SQLite Trade Audit Benchmark

A reproducible Python project showing how a composite SQLite index changes query plans, virtual-machine instructions, and execution time for common trade-audit workloads.

## Why this project exists

Trade and compliance workflows often filter executions by instrument and date or request the latest activity for one instrument. This project creates a deterministic synthetic trade dataset and measures three representative queries:

1. Point lookup by ticker and execution date
2. Date-range retrieval for one ticker
3. Five most recent executions for one ticker

Each query is benchmarked before and after creating an index on `(ticker, execution_date)`. The program captures `EXPLAIN QUERY PLAN` output and SQLite VDBE opcodes so the timing results can be connected to an actual change in execution strategy.

## Highlights

- Generates 100,000 deterministic synthetic trades with a configurable seed
- Uses parameterized SQL throughout
- Reports medians across repeated, warmed benchmark runs
- Verifies that indexing does not change query results
- Records full query plans, opcodes, and raw timing measurements in JSON
- Uses only the Python standard library
- Includes automated tests and a GitHub Actions workflow

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/jackchiang333/sqlite-trade-audit-benchmark.git
cd DSCI-551-Trade-Audit-Portfolio
python trade_audit.py
```

The default run creates 100,000 rows, executes 50 queries per repeat, takes the median of five repeats, and writes full results to `results/benchmark.json`.

Run a smaller demonstration:

```bash
python trade_audit.py --records 25000 --iterations 20 --repeats 3
```

Keep the generated SQLite database:

```bash
python trade_audit.py --database data/audit.db --output results/local.json
```

If the database already exists, add `--overwrite` explicitly.

## Example interpretation

The exact times depend on hardware and the operating-system cache. The important signals are the execution-plan changes:

- A point lookup changes from `SCAN trades` to an indexed `SEARCH`.
- A date-range query seeks to the beginning of the requested range and scans only matching index entries.
- The recent-trades query uses the index order and eliminates the temporary B-tree previously needed for `ORDER BY`.

The included `results/sample_benchmark.json` is one observed run, not a universal performance guarantee.

| Query | Rows returned | Observed speedup | Runtime reduction |
|---|---:|---:|---:|
| Point lookup | 15 | 271.42x | 99.63% |
| June date range | 416 | 12.11x | 91.74% |
| Five most recent trades | 5 | 392.52x | 99.75% |

These figures come from the included 100,000-row sample run using 50 executions per repeat and the median of five repeats.

## Test the project

```bash
python -m unittest discover -s tests -v
```

## Repository structure

```text
.
├── trade_audit.py              # Data generation, query plans, benchmark, CLI
├── tests/
│   └── test_trade_audit.py     # Correctness and reproducibility tests
├── results/
│   └── sample_benchmark.json   # One environment-specific sample run
├── BENCHMARKING.md             # Methodology and limitations
├── UPLOAD_CHECKLIST.md         # GitHub publishing checklist
├── requirements.txt            # Documents the zero-dependency setup
├── LICENSE
└── .github/workflows/tests.yml # Continuous integration
```

## Scope

This is an educational database benchmark, not a production trading or compliance system. The synthetic records contain no market or customer data. Results should be interpreted as evidence of query-plan behavior in this controlled workload, not as a latency guarantee for live trading infrastructure.

## Author

Jack Chiang  
M.S. Economics and Data Science, University of Southern California

## License

MIT License. See `LICENSE`.
