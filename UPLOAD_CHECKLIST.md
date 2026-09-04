# GitHub Upload Checklist

1. Rename the repository if desired; `sqlite-trade-audit-benchmark` is concise and professional.
2. Run `python -m unittest discover -s tests -v`.
3. Run `python trade_audit.py` and confirm the summary prints successfully.
4. Keep `results/sample_benchmark.json`; do not commit generated `.db` files.
5. Create a public GitHub repository at `jackchiang333/sqlite-trade-audit-benchmark` and upload the contents of this folder, not the outer ZIP file.
6. Add the repository URL to the Projects section of the résumé.
7. In interviews, describe the project as a controlled SQLite benchmark, not a production trading platform.

Suggested repository description:

> Reproducible Python/SQLite benchmark comparing trade-audit query plans and VDBE execution before and after composite indexing.
