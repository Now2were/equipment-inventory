import contextlib
import csv
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

import app


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'demo.sqlite'
        app.initialize(self.path, demo=True)
        self.db = app.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_duplicate_number_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            app.add_asset(self.db, 'ИНВ-001', 1, 1, 1, 100)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0], 8)

    def test_snapshot_survives_later_move(self):
        key = app.start_inventory(self.db, 'Проверка снимка')
        app.move_asset(self.db, 'ИНВ-001', 3)
        r = self.db.execute('SELECT expected_room_id FROM inventory_items '
                            'WHERE inventory_id=? AND asset_id=1', (key,)).fetchone()
        self.assertEqual(r[0], 1)
        self.assertEqual(self.db.execute('SELECT room_id FROM assets WHERE id=1').fetchone()[0], 3)

    def test_failed_move_atomic(self):
        count = self.db.execute('SELECT COUNT(*) FROM movements').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            app.move_asset(self.db, 'ИНВ-001', 999)
        self.assertEqual(self.db.execute('SELECT room_id FROM assets WHERE id=1').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM movements').fetchone()[0], count)

    def test_written_off_excluded_and_move_rejected(self):
        key = app.start_inventory(self.db, 'Состав')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM inventory_items '
                                        'WHERE inventory_id=?', (key,)).fetchone()[0], 7)
        with self.assertRaises(ValueError):
            app.move_asset(self.db, 'ИНВ-008', 1)

    def test_report_distinguishes_results(self):
        r = {x['inventory_no']: x['result'] for x in app.report(self.db, 1)}
        self.assertEqual(r['ИНВ-002'], 'кабинет')
        self.assertEqual(r['ИНВ-003'], 'отсутствует')
        self.assertEqual(r['ИНВ-005'], 'состояние')
        self.assertEqual(r['ИНВ-006'], 'не проверено')

    def test_close_requires_all_positions(self):
        with self.assertRaises(ValueError):
            app.close_inventory(self.db, 1)
        app.mark_asset(self.db, 1, 'ИНВ-006', 'found', 2, 'active')
        app.close_inventory(self.db, 1)
        with self.assertRaises(ValueError):
            app.mark_asset(self.db, 1, 'ИНВ-006', 'missing')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE inventory_items SET checked_at='changed' WHERE asset_id=1")

    def test_unknown_position_rejected(self):
        with self.assertRaises(ValueError):
            app.mark_asset(self.db, 1, 'НЕИЗВЕСТНО', 'missing')

    def test_mark_does_not_overwrite_accounting(self):
        app.mark_asset(self.db, 1, 'ИНВ-001', 'found', 3, 'repair')
        r = self.db.execute('SELECT room_id,condition FROM assets WHERE id=1').fetchone()
        self.assertEqual(tuple(r), (1, 'active'))

    def test_injection_is_literal(self):
        with self.assertRaises(ValueError):
            app.move_asset(self.db, "ИНВ-001' OR 1=1 --", 3)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0], 8)

    def test_existing_database_not_replaced(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            app.initialize(self.path, demo=True)
        self.assertEqual(before, self.path.read_bytes())

    def test_csv_unicode_and_formula_literal(self):
        app.add_asset(self.db, '=2+2', 1, 1, 1, 100)
        key = app.start_inventory(self.db, 'Экспорт')
        target = Path(self.temp.name) / 'output.csv'
        self.assertEqual(app.export_csv(self.db, key, target), 8)
        with target.open(encoding='utf-8-sig', newline='') as f:
            data = list(csv.DictReader(f, delimiter=';'))
        self.assertIn("'=2+2", [r['inventory_no'] for r in data])
        with self.assertRaises(FileExistsError):
            app.export_csv(self.db, key, target)

    def test_cli_error_exit(self):
        with contextlib.redirect_stderr(io.StringIO()) as out:
            code = app.main(['--db', str(self.path), 'close', '--inventory', '1'])
        self.assertEqual(code, 1)
        self.assertIn('непроверенные', out.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
