"""Локальный учебный модуль учёта техники. Только стандартная библиотека."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from verify_queries import load_queries


def now() -> str:
    return datetime.now(timezone(timedelta(hours=3))).isoformat(timespec='seconds')


def connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError('База не найдена. Сначала выполните init.')
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize(path: Path, demo: bool = False):
    # exclusive creation protects an existing database from accidental reset.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb'):
        pass
    db = sqlite3.connect(path)
    try:
        db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        if demo:
            db.executescript((ROOT / 'demo.sql').read_text(encoding='utf-8'))
        db.commit()
    finally:
        db.close()


def rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params)]


def require_open(db, inventory_id):
    r = db.execute('SELECT status FROM inventories WHERE id=?', (inventory_id,)).fetchone()
    if not r:
        raise ValueError('Инвентаризация не найдена.')
    if r['status'] != 'open':
        raise ValueError('Инвентаризация уже закрыта.')


def add_asset(db, number, model, room, custodian, cost, condition='active'):
    if not number.strip() or number != number.strip():
        raise ValueError('Номер должен быть непустым и без пробелов по краям.')
    with db:
        cur = db.execute(
            'INSERT INTO assets(inventory_no,model_id,room_id,custodian_id,cost_kopecks,condition) '
            'VALUES (?,?,?,?,?,?)', (number, model, room, custodian, cost, condition))
        return cur.lastrowid


def move_asset(db, number, room, note=''):
    with db:
        db.execute('BEGIN IMMEDIATE')
        asset = db.execute('SELECT id,room_id,condition FROM assets WHERE inventory_no=?',
                           (number,)).fetchone()
        if not asset:
            raise ValueError('Оборудование не найдено.')
        if asset['condition'] == 'written_off':
            raise ValueError('Списанное оборудование перемещать нельзя.')
        if asset['room_id'] == room:
            raise ValueError('Оборудование уже находится в этом кабинете.')
        db.execute('INSERT INTO movements(asset_id,from_room_id,to_room_id,moved_at,note) '
                   'VALUES (?,?,?,?,?)', (asset['id'], asset['room_id'], room, now(), note))
        db.execute('UPDATE assets SET room_id=? WHERE id=?', (room, asset['id']))


def start_inventory(db, title):
    if not title.strip():
        raise ValueError('Название проверки не может быть пустым.')
    with db:
        db.execute('BEGIN IMMEDIATE')
        count = db.execute("SELECT COUNT(*) FROM assets WHERE condition<>'written_off'").fetchone()[0]
        if not count:
            raise ValueError('Нет несписанного оборудования для проверки.')
        cur = db.execute('INSERT INTO inventories(title,started_at) VALUES (?,?)', (title, now()))
        key = cur.lastrowid
        db.execute('INSERT INTO inventory_items '
                   '(inventory_id,asset_id,expected_room_id,expected_custodian_id,expected_condition) '
                   "SELECT ?,id,room_id,custodian_id,condition FROM assets WHERE condition<>'written_off'",
                   (key,))
        return key


def mark_asset(db, inventory_id, number, presence, room=None, condition=None):
    if presence not in ('found', 'missing'):
        raise ValueError('Допустимые результаты: found или missing.')
    if presence == 'found' and (room is None or condition is None):
        raise ValueError('Для найденной техники нужны кабинет и состояние.')
    if presence == 'missing' and (room is not None or condition is not None):
        raise ValueError('Для отсутствующей техники кабинет и состояние не задаются.')
    with db:
        db.execute('BEGIN IMMEDIATE')
        require_open(db, inventory_id)
        cur = db.execute('UPDATE inventory_items SET presence=?, observed_room_id=?, '
                         'observed_condition=?, checked_at=? WHERE inventory_id=? '
                         'AND asset_id=(SELECT id FROM assets WHERE inventory_no=?)',
                         (presence, room, condition, now(), inventory_id, number))
        if cur.rowcount != 1:
            raise ValueError('Оборудование не входит в эту инвентаризацию.')


def close_inventory(db, key):
    with db:
        db.execute('BEGIN IMMEDIATE')
        require_open(db, key)
        count = db.execute("SELECT COUNT(*) FROM inventory_items WHERE inventory_id=? "
                           "AND presence='unchecked'", (key,)).fetchone()[0]
        if count:
            raise ValueError(f'Остались непроверенные позиции: {count}.')
        db.execute("UPDATE inventories SET status='closed',closed_at=? WHERE id=?", (now(), key))


def report(db, key):
    if not db.execute('SELECT 1 FROM inventories WHERE id=?', (key,)).fetchone():
        raise ValueError('Инвентаризация не найдена.')
    return rows(db, '''SELECT a.inventory_no, m.name AS model,
        er.code AS expected_room, ec.name AS expected_custodian,
        i.expected_condition, i.presence, rr.code AS observed_room,
        i.observed_condition,
        CASE WHEN i.presence='unchecked' THEN 'не проверено'
             WHEN i.presence='missing' THEN 'отсутствует'
             WHEN i.expected_room_id<>i.observed_room_id
               AND i.expected_condition<>i.observed_condition THEN 'кабинет и состояние'
             WHEN i.expected_room_id<>i.observed_room_id THEN 'кабинет'
             WHEN i.expected_condition<>i.observed_condition THEN 'состояние'
             ELSE 'совпадает' END AS result
        FROM inventory_items i JOIN assets a ON a.id=i.asset_id
        JOIN models m ON m.id=a.model_id
        JOIN rooms er ON er.id=i.expected_room_id
        JOIN custodians ec ON ec.id=i.expected_custodian_id
        LEFT JOIN rooms rr ON rr.id=i.observed_room_id
        WHERE i.inventory_id=? ORDER BY a.inventory_no''', (key,))


def export_csv(db, key, target):
    data = report(db, key)
    if not data:
        raise ValueError('В проверке нет позиций.')
    # UTF-8 BOM and semicolons allow opening Russian text in spreadsheet tools.
    with target.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0]), delimiter=';')
        writer.writeheader()
        for row in data:
            # Values beginning with formula markers remain literal spreadsheet text.
            safe = {k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@'))
                        else v) for k, v in row.items()}
            writer.writerow(safe)
    return len(data)


def parser():
    p = argparse.ArgumentParser(description='Учебный модуль инвентаризации оборудования')
    p.add_argument('--db', type=Path, default=ROOT / 'inventory.sqlite')
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('init', help='создать новую БД'); q.add_argument('--demo', action='store_true')
    sub.add_parser('refs', help='показать справочники')
    for cmd in ('add-manufacturer', 'add-custodian'):
        q = sub.add_parser(cmd); q.add_argument('--name', required=True)
    q = sub.add_parser('add-room'); q.add_argument('--code', required=True); q.add_argument('--title', required=True)
    q = sub.add_parser('add-model')
    q.add_argument('--manufacturer', type=int, required=True); q.add_argument('--name', required=True)
    q.add_argument('--kind', choices=['PC', 'Laptop', 'Printer'], required=True)
    for field in ('cpu', 'ram', 'disk', 'color'):
        q.add_argument('--'+field, type=int)
    q.add_argument('--screen', type=float)
    q = sub.add_parser('add-asset')
    q.add_argument('--number', required=True)
    for field in ('model', 'room', 'custodian', 'cost'):
        q.add_argument('--'+field, type=int, required=True)
    q.add_argument('--condition', choices=['active', 'repair', 'written_off'], default='active')
    q = sub.add_parser('list'); q.add_argument('--room', type=int)
    q.add_argument('--kind', choices=['PC', 'Laptop', 'Printer'])
    q = sub.add_parser('move'); q.add_argument('--number', required=True)
    q.add_argument('--room', type=int, required=True); q.add_argument('--note', default='')
    q = sub.add_parser('start'); q.add_argument('--title', required=True)
    q = sub.add_parser('mark'); q.add_argument('--number', required=True)
    q.add_argument('--inventory', type=int, required=True)
    q.add_argument('--presence', choices=['found', 'missing'], required=True)
    q.add_argument('--room', type=int)
    q.add_argument('--condition', choices=['active', 'repair', 'written_off'])
    for cmd in ('close', 'report', 'export'):
        q = sub.add_parser(cmd); q.add_argument('--inventory', type=int, required=True)
        if cmd == 'export': q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('query'); q.add_argument('key', choices=list(load_queries()))
    q.add_argument('--params', default='{}', help='параметры JSON')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'init':
            initialize(args.db, args.demo)
            print('База создана. Демонстрационные данные вымышлены.' if args.demo else 'Пустая база создана.')
            return 0
        db = connect(args.db)
        try:
            c = args.command
            if c == 'refs':
                output = {name: rows(db, 'SELECT * FROM '+name+' ORDER BY id')
                          for name in ('manufacturers', 'models', 'rooms', 'custodians')}
            elif c in ('add-manufacturer', 'add-custodian'):
                table = {'add-manufacturer': 'manufacturers', 'add-custodian': 'custodians'}[c]
                with db:
                    output = {'id': db.execute('INSERT INTO '+table+'(name) VALUES (?)',
                                              (args.name,)).lastrowid}
            elif c == 'add-room':
                with db:
                    output = {'id': db.execute('INSERT INTO rooms(code,title) VALUES (?,?)',
                                              (args.code, args.title)).lastrowid}
            elif c == 'add-model':
                with db:
                    output = {'id': db.execute('INSERT INTO models '
                        '(manufacturer_id,name,kind,cpu_mhz,ram_gb,disk_gb,screen_inch,color) '
                        'VALUES (?,?,?,?,?,?,?,?)', (args.manufacturer,args.name,args.kind,
                        args.cpu,args.ram,args.disk,args.screen,args.color)).lastrowid}
            elif c == 'add-asset':
                output = {'id': add_asset(db,args.number,args.model,args.room,
                                         args.custodian,args.cost,args.condition)}
            elif c == 'list':
                output = rows(db, '''SELECT a.inventory_no,m.name,m.kind,r.code AS room,
                    a.condition,a.cost_kopecks / 100.0 AS cost_rub FROM assets a
                    JOIN models m ON m.id=a.model_id JOIN rooms r ON r.id=a.room_id
                    WHERE (? IS NULL OR a.room_id=?) AND (? IS NULL OR m.kind=?)
                    ORDER BY a.inventory_no''', (args.room,args.room,args.kind,args.kind))
            elif c == 'move':
                move_asset(db,args.number,args.room,args.note); output = {'result': 'Перемещение сохранено'}
            elif c == 'start': output = {'inventory_id': start_inventory(db,args.title)}
            elif c == 'mark':
                mark_asset(db,args.inventory,args.number,args.presence,args.room,args.condition)
                output = {'result': 'Результат проверки сохранён'}
            elif c == 'close':
                close_inventory(db,args.inventory); output = {'result': 'Инвентаризация закрыта'}
            elif c == 'report': output = report(db,args.inventory)
            elif c == 'export':
                output = {'exported': export_csv(db,args.inventory,args.out), 'file': str(args.out)}
            elif c == 'query':
                parameters = json.loads(args.params)
                if not isinstance(parameters, dict):
                    raise ValueError('Параметры должны быть объектом JSON.')
                output = rows(db, load_queries()[args.key], parameters)
            print(json.dumps(output,ensure_ascii=False,indent=2))
        finally:
            db.close()
        return 0
    except (ValueError, OSError, sqlite3.Error) as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
