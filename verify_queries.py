"""Проверка SQL на демонстрационных данных без изменения файлов БД."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parent


def load_queries() -> dict[str, str]:
    text = (ROOT / 'queries.sql').read_text(encoding='utf-8')
    blocks = re.split(r'(?m)^-- (Q\d{2}) [^\n]*\n', text)
    return {blocks[i]: blocks[i + 1].strip() for i in range(1, len(blocks), 2)}


PARAMS = {
    'min_ram': 16, 'min_cost': 6000000, 'min_disk': 256,
    'manufacturer': 'Север', 'min_count': 3, 'inventory_id': 1,
}
EXPECTED = {
    'Q01': [('ИНВ-001', 'Учебный ПК 16', 16), ('ИНВ-002', 'Учебный ПК 16', 16)],
    'Q02': [('Печать',)],
    'Q03': [('ИНВ-003', 'Ноутбук 8', 8, 15.6, 60000.0),
            ('ИНВ-007', 'Ноутбук 8', 8, 15.6, 60000.0)],
    'Q04': [('ИНВ-004', 'Принтер Цвет')],
    'Q05': [('Вектор', 2400), ('Вектор', 3000)],
    'Q06': [('ИНВ-001', 'PC', 'Учебный ПК 16', 70000.0),
            ('ИНВ-002', 'PC', 'Учебный ПК 16', 70000.0),
            ('ИНВ-005', 'PC', 'Учебный ПК 8', 40000.0)],
    'Q07': [('Север',)],
    'Q08': [('ИНВ-004', 'Принтер Цвет', 35000.0)],
    'Q09': [(51428.57,)],
    'Q10': [('101', 2), ('102', 3), ('201', 2), ('202', 0)],
    'Q11': [('102', 3)],
    'Q12': [('Laptop', 2, 28.57), ('PC', 3, 42.86), ('Printer', 2, 28.57)],
    'Q13': [('Резерв', 0), ('Север', 3)],
    'Q14': [('ИНВ-002', 'found', 0, 1, 0), ('ИНВ-003', 'missing', 1, 0, 0),
             ('ИНВ-005', 'found', 0, 0, 1)],
    'Q15': [('ИНВ-006', '102')],
    'Q16': [('ИНВ-002', '101', '102', '2026-10-15T10:01:00+03:00')],
}


def database(demo: bool = True) -> sqlite3.Connection:
    con = sqlite3.connect(':memory:')
    con.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    if demo:
        con.executescript((ROOT / 'demo.sql').read_text(encoding='utf-8'))
    return con


def verify() -> dict:
    queries = load_queries()
    checks: list[dict] = []
    results: dict = {}

    def check(name: str, actual, expected):
        if actual != expected:
            raise AssertionError(f'{name}: expected {expected!r}, got {actual!r}')
        checks.append({'name': name, 'status': 'passed'})

    with database() as con:
        for key, sql in queries.items():
            cur = con.execute(sql, PARAMS)
            rows = cur.fetchall()
            check(key, rows, EXPECTED[key])
            results[key] = {'columns': [c[0] for c in cur.description], 'rows': rows}
        check('snapshot_survives_move', con.execute(
            'SELECT i.expected_room_id, a.room_id FROM inventory_items i '
            'JOIN assets a ON a.id=i.asset_id WHERE i.asset_id=2'
        ).fetchall(), [(1, 2)])
        check('literal_parameter', con.execute(queries['Q06'], {
            **PARAMS, 'manufacturer': "Север' OR 1=1 --"
        }).fetchall(), [])
        check('foreign_key_check', con.execute('PRAGMA foreign_key_check').fetchall(), [])
        check('integrity_check', con.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        # Оба принтера получают одинаковую максимальную стоимость.
        con.execute('UPDATE assets SET cost_kopecks=3500000 WHERE id=6')
        check('equal_maxima', len(con.execute(queries['Q08']).fetchall()), 2)
        # При одинаковом времени последним считается перемещение с большим id.
        con.execute("INSERT INTO movements VALUES (2,2,2,3,'2026-10-15T10:01:00+03:00','test')")
        check('movement_time_tie', con.execute(queries['Q16']).fetchone()[2], '201')

    with database(demo=False) as con:
        check('empty_average', con.execute(queries['Q09']).fetchall(), [(None,)])
        check('empty_distribution', con.execute(queries['Q12']).fetchall(),
              [('Laptop', 0, 0.0), ('PC', 0, 0.0), ('Printer', 0, 0.0)])
        check('empty_maximum', con.execute(queries['Q08']).fetchall(), [])

    for name, sql, values in [
        ('duplicate_inventory_no',
         'INSERT INTO assets VALUES (9,?,?,?,?,?,?)',
         ('ИНВ-001', 1, 1, 1, 100, 'active')),
        ('unknown_room', 'UPDATE assets SET room_id=? WHERE id=?', (999, 1)),
        ('negative_cost', 'UPDATE assets SET cost_kopecks=? WHERE id=?', (-1, 1)),
        ('fractional_kopecks', 'UPDATE assets SET cost_kopecks=? WHERE id=?', (1.5, 1)),
        ('found_without_room',
         "UPDATE inventory_items SET presence='found', checked_at='test', "
         "observed_condition='active' WHERE asset_id=6", ()),
        ('premature_close',
         "UPDATE inventories SET status='closed', closed_at='test' WHERE id=1", ()),
    ]:
        with database() as con:
            try:
                con.execute(sql, values)
            except sqlite3.IntegrityError:
                checks.append({'name': name, 'status': 'passed'})
            else:
                raise AssertionError(f'{name}: expected IntegrityError')

    with database() as con:
        con.execute("UPDATE inventory_items SET presence='missing', checked_at='test' "
                    "WHERE presence='unchecked'")
        con.execute("UPDATE inventories SET status='closed', closed_at='test' WHERE id=1")
        try:
            con.execute("UPDATE inventory_items SET checked_at='changed' WHERE asset_id=1")
        except sqlite3.IntegrityError:
            checks.append({'name': 'closed_inventory_immutable', 'status': 'passed'})
        else:
            raise AssertionError('closed inventory unexpectedly editable')

    return {'scope': 'SQL и ограничения схемы, этапы 2 и 3',
            'sqlite_version': sqlite3.sqlite_version,
            'passed': len(checks), 'failed': 0,
            'checks': checks, 'query_results': results}


if __name__ == '__main__':
    report = verify()
    target = ROOT / 'Результаты проверки SQL.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Проверок пройдено: {report['passed']}; ошибок: {report['failed']}")
    print(f'Результаты: {target.name}')
