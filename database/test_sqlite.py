
"""Tests for the WaterWatch SQLite store-and-forward manager."""

import logging
import tempfile

from pathlib import Path

from database.sqlite_manager import SQLiteManager


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def run_test():
    with tempfile.TemporaryDirectory() as temp_dir:

        database_file = Path(temp_dir) / "test_waterwatch.db"

        # Small capacity makes eviction easy to test.
        db = SQLiteManager(
            database_path=database_file,
            max_buffer_size=3
        )

        print("\nTEST 1: Inserting readings")

        for timestamp in [1000, 2000, 3000, 4000]:
            payload = {
                "ts": timestamp,
                "ph": 7.2,
                "turbidity_ntu": 5.0,
                "tds_ppm": 180,
                "water_temp_c": 20.0,
                "flow_lpm": 12.0,
                "latitude": 28.1053,
                "longitude": 85.3076915
            }

            db.insert_reading("rasuwa", payload)

        print("\nTEST 2: Checking buffer capacity")

        stats = db.get_statistics()
        print(stats)

        assert stats["pending_readings"] == 3
        assert stats["evicted_readings"] == 1

        print("\nTEST 3: Checking chronological order")

        batch = db.get_pending_batch(batch_size=10)

        timestamps = [
            reading["timestamp_ms"]
            for reading in batch
        ]

        print("Pending timestamps:", timestamps)

        assert timestamps == [2000, 3000, 4000]

        print("\nTEST 4: Checking original timestamps")

        assert batch[0]["payload"]["ts"] == 2000

        print("\nTEST 5: Marking a reading as synced")

        db.mark_synced([batch[0]["id"]])

        assert db.get_pending_count() == 2
        assert db.get_synced_count() == 1

        print("\nALL SQLITE TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_test()
