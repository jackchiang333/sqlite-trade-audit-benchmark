import sqlite3
import tempfile
import unittest
from pathlib import Path

import trade_audit


class TradeAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.connection = trade_audit.connect_database(self.db_path)
        trade_audit.create_schema(self.connection)
        trade_audit.populate_database(self.connection, 10_000, seed=7)
        self.queries = trade_audit.build_queries(
            "AAPL", "2025-06-15", "2025-06-01", "2025-06-30"
        )

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_expected_record_count(self) -> None:
        count = self.connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        self.assertEqual(count, 10_000)

    def test_data_generation_is_reproducible(self) -> None:
        other = sqlite3.connect(":memory:")
        try:
            trade_audit.create_schema(other)
            trade_audit.populate_database(other, 10_000, seed=7)
            first = self.connection.execute(
                "SELECT * FROM trades ORDER BY id LIMIT 25"
            ).fetchall()
            second = other.execute(
                "SELECT * FROM trades ORDER BY id LIMIT 25"
            ).fetchall()
            self.assertEqual(first, second)
        finally:
            other.close()

    def test_index_preserves_results_and_changes_plan(self) -> None:
        results_before = {
            query.name: trade_audit.execute_query(self.connection, query)
            for query in self.queries
        }
        plans_before = {
            query.name: trade_audit.explain_query_plan(self.connection, query)
            for query in self.queries
        }

        trade_audit.create_composite_index(self.connection)

        for query in self.queries:
            self.assertEqual(
                sorted(results_before[query.name]),
                sorted(trade_audit.execute_query(self.connection, query)),
            )
            indexed_plan = " ".join(
                trade_audit.explain_query_plan(self.connection, query)
            )
            self.assertIn(trade_audit.INDEX_NAME, indexed_plan)
            self.assertNotEqual(" ".join(plans_before[query.name]), indexed_plan)

    def test_invalid_date_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            trade_audit.build_queries(
                "AAPL", "2025-06-15", "2025-07-01", "2025-06-01"
            )

    def test_parameterized_query_treats_input_as_data(self) -> None:
        query = trade_audit.build_queries(
            "AAPL' OR 1=1 --", "2025-06-15", "2025-06-01", "2025-06-30"
        )[0]
        self.assertEqual(trade_audit.execute_query(self.connection, query), [])


if __name__ == "__main__":
    unittest.main()
