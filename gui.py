"""Графический интерфейс локального модуля инвентаризации."""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import app

# В сборке база хранится рядом с EXE, а не во временной папке распаковки.
ROOT = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
KINDS = {'PC': 'Компьютер', 'Laptop': 'Ноутбук', 'Printer': 'Принтер'}
CONDITIONS = {'active': 'Исправно', 'repair': 'В ремонте', 'written_off': 'Списано'}
PRESENCE = {'unchecked': 'Не проверено', 'found': 'Найдено', 'missing': 'Отсутствует'}
REFS = {'Производители': 'manufacturers', 'Модели': 'models',
        'Кабинеты': 'rooms', 'Ответственные лица': 'custodians'}


def rubles_to_kopecks(value):
    try:
        amount = Decimal(str(value).strip().replace(' ', '').replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Введите стоимость числом, например 75000 или 75000,50.') from None
    if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError('Стоимость должна быть неотрицательной, не более двух знаков после запятой.')
    return int(amount * 100)


def money(kopecks):
    return f'{kopecks / 100:,.2f}'.replace(',', ' ').replace('.', ',')


def friendly_error(error):
    s = str(error)
    if isinstance(error, FileExistsError):
        return 'Файл с таким именем уже существует. Выберите другое имя, чтобы сохранить предыдущие данные.'
    if 'UNIQUE constraint failed: assets.inventory_no' in s:
        return 'Этот инвентарный номер уже используется. Укажите другой.'
    if 'UNIQUE constraint failed' in s:
        return 'Такая запись уже существует. Проверьте название или номер.'
    if 'FOREIGN KEY constraint failed' in s:
        return 'Связанная запись не найдена. Обновите справочники и повторите действие.'
    if 'CHECK constraint failed' in s:
        return 'Проверьте значения: названия не должны быть пустыми, числовые характеристики должны быть положительными.'
    if 'database is locked' in s:
        return 'База занята другой операцией. Повторите действие немного позже.'
    if 'closed inventory' in s:
        return 'Проверка уже закрыта. Её результаты доступны только для просмотра.'
    return s


class EntryDialog(tk.Toplevel):
    """Небольшая форма с именованными полями и русскими подписями."""
    def __init__(self, owner, title, fields, submit):
        super().__init__(owner)
        self.title(title)
        self.transient(owner)
        self.resizable(False, False)
        self.submit = submit
        self.variables = {}
        self.fields = fields
        outer = ttk.Frame(self, padding=24)
        outer.grid(sticky='nsew')
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text=title, style='Section.TLabel').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 18))
        self.widgets = {}
        for i, field in enumerate(fields, 1):
            key, label, options, default = field
            ttk.Label(outer, text=label).grid(row=i, column=0, sticky='w', padx=(0, 18), pady=7)
            var = tk.StringVar(value=default)
            self.variables[key] = var
            if options is None:
                widget = ttk.Entry(outer, textvariable=var, width=38)
            else:
                widget = ttk.Combobox(outer, textvariable=var, values=list(options), state='readonly', width=36)
                if default not in options and options:
                    var.set(next(iter(options)))
            widget.grid(row=i, column=1, sticky='ew', pady=7)
            self.widgets[key] = widget
        buttons = ttk.Frame(outer)
        buttons.grid(row=len(fields)+1, column=0, columnspan=2, sticky='e', pady=(20, 0))
        ttk.Button(buttons, text='Отмена', command=self.destroy).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Сохранить', style='Primary.TButton', command=self.save).pack(side='left')
        self.bind('<Escape>', lambda _: self.destroy())
        self.bind('<Return>', lambda _: self.save())
        self.update_idletasks()
        x = owner.winfo_rootx() + max(0, (owner.winfo_width()-self.winfo_width())//2)
        y = owner.winfo_rooty() + max(0, (owner.winfo_height()-self.winfo_height())//2)
        self.geometry(f'+{x}+{y}')
        self.grab_set()
        if self.widgets:
            self.after(50, next(iter(self.widgets.values())).focus_set)

    def save(self):
        try:
            data = {}
            for key, label, options, default in self.fields:
                value = self.variables[key].get().strip()
                if options is not None:
                    if value not in options:
                        raise ValueError(f'Выберите значение поля «{label}».')
                    value = options[value]
                data[key] = value
            self.submit(data)
        except (ValueError, sqlite3.Error, OSError) as error:
            messagebox.showerror('Не удалось сохранить', friendly_error(error), parent=self)
            return
        self.destroy()


class InventoryWindow(tk.Tk):
    def __init__(self, db_path):
        super().__init__()
        self.title('Учёт оборудования — Инвентаризация')
        self.geometry('1220x800')
        self.minsize(1000, 650)
        self.configure(bg='#f2f5f9')
        self.db_path = Path(db_path)
        self.db = None
        self.inventory_map = {}
        self.inventory_rows = {}
        self.inventory_status = None
        self.assets = {}
        self._styles()
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<F5>', lambda _: self.refresh())
        self.report_callback_exception = self.callback_error
        try:
            fresh = not self.db_path.exists()
            if fresh:
                app.initialize(self.db_path, demo=True)
            self.use_database(self.db_path)
            self.status.set('Создан учебный пример с вымышленными данными.' if fresh else 'Готово. Выберите оборудование или откройте вкладку «Инвентаризация».')
        except (ValueError, sqlite3.Error, OSError) as error:
            messagebox.showerror('Не удалось открыть базу', friendly_error(error), parent=self)
            if self.db is not None:
                self.db.close()
                self.db = None
            self.destroy()

    def _styles(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('.', font=('Segoe UI', 10), background='#f2f5f9', foreground='#172b43')
        s.configure('TFrame', background='#f2f5f9')
        s.configure('TButton', padding=(13, 8), background='#e5ebf2', borderwidth=0)
        s.map('TButton', background=[('active', '#d5dfeb')], foreground=[('disabled', '#8895a5')])
        s.configure('Primary.TButton', background='#245dcc', foreground='white')
        s.map('Primary.TButton', background=[('active', '#174cb2'), ('disabled', '#c4d1e4')], foreground=[('disabled', '#f5f7fa')])
        s.configure('Section.TLabel', font=('Segoe UI', 16, 'bold'))
        s.configure('Muted.TLabel', foreground='#60738a')
        s.configure('TNotebook', background='#f2f5f9', borderwidth=0)
        s.configure('TNotebook.Tab', padding=(20, 12), background='#e5ebf2')
        s.map('TNotebook.Tab', background=[('selected', '#ffffff')], foreground=[('selected', '#245dcc')])
        s.configure('Treeview', background='white', fieldbackground='white', rowheight=35, borderwidth=0, font=('Segoe UI', 10))
        s.configure('Treeview.Heading', background='#e9eef5', font=('Segoe UI', 10, 'bold'), padding=9, relief='flat')
        s.map('Treeview', background=[('selected', '#dce9ff')], foreground=[('selected', '#153969')])
        s.configure('TEntry', padding=7)
        s.configure('TCombobox', padding=5)

    def _build(self):
        header = tk.Frame(self, bg='#183449', padx=26, pady=20)
        header.pack(fill='x')
        tk.Label(header, text='Учёт оборудования', font=('Segoe UI', 23, 'bold'), fg='white', bg='#183449').pack(anchor='w')
        tk.Label(header, text='Карточки техники, перемещения и проверка наличия', font=('Segoe UI', 10), fg='#c4d6e5', bg='#183449').pack(anchor='w', pady=(5, 0))
        toolbar = ttk.Frame(self, padding=(24, 12))
        toolbar.pack(fill='x')
        self.summary = tk.StringVar()
        ttk.Label(toolbar, textvariable=self.summary, style='Muted.TLabel').pack(side='left')
        ttk.Button(toolbar, text='Обновить', command=self.refresh).pack(side='right', padx=(8, 0))
        ttk.Button(toolbar, text='База данных…', command=self.database_menu).pack(side='right')
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=24, pady=(0, 14))
        self.equipment_tab = ttk.Frame(self.notebook, padding=18)
        self.check_tab = ttk.Frame(self.notebook, padding=18)
        self.refs_tab = ttk.Frame(self.notebook, padding=18)
        self.history_tab = ttk.Frame(self.notebook, padding=18)
        for frame, name in [(self.equipment_tab, 'Оборудование'), (self.check_tab, 'Инвентаризация'), (self.refs_tab, 'Справочники'), (self.history_tab, 'Перемещения')]:
            self.notebook.add(frame, text=name)
        self._equipment()
        self._inventories()
        self._references()
        self._history()
        bottom = ttk.Frame(self, padding=(24, 4, 24, 14))
        bottom.pack(side='bottom', fill='x', before=self.notebook)
        self.status = tk.StringVar(value='Открытие базы…')
        ttk.Label(bottom, textvariable=self.status, style='Muted.TLabel', wraplength=900).pack(anchor='w')

    def _tree(self, parent, columns, widths):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=(12, 0))
        keys = [f'c{i}' for i in range(len(columns))]
        tree = ttk.Treeview(frame, columns=keys, show='headings', selectmode='browse')
        for key, title, width in zip(keys, columns, widths):
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=70, stretch=True)
        y = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        x = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        tree.grid(row=0, column=0, sticky='nsew')
        y.grid(row=0, column=1, sticky='ns')
        x.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
        tree.tag_configure('warning', background='#fff1e5')
        tree.tag_configure('pending', background='#f0f4fa')
        return tree

    def _equipment(self):
        controls = ttk.Frame(self.equipment_tab); controls.pack(fill='x')
        ttk.Label(controls, text='Номер или модель').pack(side='left', padx=(0, 8))
        self.search = tk.StringVar()
        ttk.Entry(controls, textvariable=self.search, width=22).pack(side='left', padx=(0, 12))
        self.kind = tk.StringVar(value='Все типы')
        ttk.Combobox(controls, textvariable=self.kind, state='readonly', values=['Все типы', *KINDS.values()], width=17).pack(side='left')
        ttk.Button(controls, text='Добавить оборудование', style='Primary.TButton', command=self.add_equipment).pack(side='right')
        ttk.Button(controls, text='Переместить', command=self.move_equipment).pack(side='right', padx=8)
        self.assets_tree = self._tree(self.equipment_tab,
            ['Инвентарный номер', 'Модель', 'Тип', 'Кабинет', 'Ответственный', 'Состояние', 'Стоимость, ₽'], [150, 195, 115, 95, 165, 105, 125])
        self.assets_tree.bind('<Double-1>', lambda _: self.asset_details())
        self.search.trace_add('write', lambda *_: self.refresh_assets())
        self.kind.trace_add('write', lambda *_: self.refresh_assets())
        ttk.Label(self.equipment_tab, text='Выберите строку для перемещения. Двойной щелчок открывает карточку.', style='Muted.TLabel').pack(anchor='w', pady=(10, 0))

    def _inventories(self):
        top = ttk.Frame(self.check_tab); top.pack(fill='x')
        ttk.Label(top, text='Проверка').pack(side='left', padx=(0, 8))
        self.inventory_var = tk.StringVar()
        self.inventory_combo = ttk.Combobox(top, textvariable=self.inventory_var, state='readonly', width=55)
        self.inventory_combo.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.inventory_combo.bind('<<ComboboxSelected>>', lambda _: self.refresh_inventory())
        ttk.Button(top, text='Новая проверка', style='Primary.TButton', command=self.new_inventory).pack(side='right')
        actions = ttk.Frame(self.check_tab); actions.pack(fill='x', pady=(14, 0))
        self.found_button = ttk.Button(actions, text='Найдено', command=self.mark_found)
        self.found_button.pack(side='left')
        self.missing_button = ttk.Button(actions, text='Отсутствует', command=self.mark_missing)
        self.missing_button.pack(side='left', padx=8)
        self.close_button = ttk.Button(actions, text='Завершить проверку', command=self.finish_inventory)
        self.close_button.pack(side='right')
        self.export_button = ttk.Button(actions, text='Сохранить CSV', command=self.export_inventory)
        self.export_button.pack(side='right', padx=8)
        self.check_summary = tk.StringVar()
        ttk.Label(self.check_tab, textvariable=self.check_summary, style='Muted.TLabel').pack(anchor='w', pady=(12, 0))
        self.check_tree = self._tree(self.check_tab,
            ['Инвентарный номер', 'Модель', 'Учётный кабинет', 'Фактический кабинет', 'Наличие', 'Результат'], [150, 185, 130, 140, 130, 175])
        self.check_tree.bind('<Double-1>', lambda _: self.mark_found())
        ttk.Label(self.check_tab, text='Выберите оборудование и отметьте результат. Непроверенные позиции нельзя считать отсутствующими.', style='Muted.TLabel').pack(anchor='w', pady=(10, 0))

    def _references(self):
        line = ttk.Frame(self.refs_tab); line.pack(fill='x')
        self.ref_kind = tk.StringVar(value='Кабинеты')
        combo = ttk.Combobox(line, values=list(REFS), textvariable=self.ref_kind, state='readonly', width=26)
        combo.pack(side='left'); combo.bind('<<ComboboxSelected>>', lambda _: self.refresh_references())
        ttk.Button(line, text='Добавить запись', style='Primary.TButton', command=self.add_reference).pack(side='right')
        self.refs_tree = self._tree(self.refs_tab, ['Название', 'Дополнительные сведения'], [340, 650])
        ttk.Label(self.refs_tab, text='Сначала добавьте производителя, модель, кабинет и ответственное лицо, затем создайте карточку техники.', style='Muted.TLabel').pack(anchor='w', pady=(10, 0))

    def _history(self):
        ttk.Label(self.history_tab, text='История перемещений', style='Section.TLabel').pack(anchor='w')
        self.history_tree = self._tree(self.history_tab, ['Дата и время', 'Инвентарный номер', 'Откуда', 'Куда', 'Примечание'], [165, 160, 100, 100, 455])

    def callback_error(self, kind, value, trace):
        messagebox.showerror('Действие не выполнено', friendly_error(value), parent=self)

    def use_database(self, path):
        candidate = app.connect(path)
        expected = set(REFS.values()) | {'assets', 'inventories', 'inventory_items', 'movements'}
        existing = {r[0] for r in candidate.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not expected <= existing:
            candidate.close()
            raise ValueError('Выбранный файл не является базой этого проекта.')
        if self.db is not None:
            self.db.close()
        self.db = candidate
        self.db_path = Path(path)
        self.inventory_var.set('')
        self.title(f'Учёт оборудования — {self.db_path.name}')
        self.refresh()

    def database_menu(self):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label='Открыть существующую базу…', command=self.open_database)
        menu.add_command(label='Создать учебную базу…', command=lambda: self.new_database(True))
        menu.add_command(label='Создать пустую базу…', command=lambda: self.new_database(False))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def open_database(self):
        path = filedialog.askopenfilename(parent=self, title='Открыть базу проекта', filetypes=[('База SQLite', '*.sqlite *.db'), ('Все файлы', '*.*')])
        if path:
            self.use_database(Path(path)); self.status.set(f'Открыта база «{Path(path).name}».')

    def new_database(self, demo):
        path = filedialog.asksaveasfilename(parent=self, title='Новая база', defaultextension='.sqlite', initialfile='учебная.sqlite' if demo else 'оборудование.sqlite', filetypes=[('База SQLite', '*.sqlite')])
        if path:
            app.initialize(Path(path), demo=demo)
            self.use_database(Path(path))
            self.status.set('Создана новая учебная база.' if demo else 'Создана пустая база. Начните со вкладки «Справочники».')

    def refresh(self):
        if self.db is None:
            return
        total = self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
        rooms = self.db.execute('SELECT COUNT(*) FROM rooms').fetchone()[0]
        opened = self.db.execute("SELECT COUNT(*) FROM inventories WHERE status='open'").fetchone()[0]
        self.summary.set(f'Оборудование: {total}     Кабинеты: {rooms}     Открытые проверки: {opened}')
        self.refresh_assets()
        self.refresh_inventory_list()
        self.refresh_references()
        self.refresh_history()

    @staticmethod
    def clear(tree):
        for item in tree.get_children(): tree.delete(item)

    def refresh_assets(self):
        if self.db is None:
            return
        self.clear(self.assets_tree)
        self.assets = {}
        term = self.search.get().strip().casefold()
        kind = next((k for k, v in KINDS.items() if v == self.kind.get()), None)
        data = app.rows(self.db, '''SELECT a.*,m.name AS model,m.kind,r.code AS room,c.name AS custodian
            FROM assets a JOIN models m ON m.id=a.model_id JOIN rooms r ON r.id=a.room_id
            JOIN custodians c ON c.id=a.custodian_id ORDER BY a.inventory_no''')
        for record in data:
            if kind and record['kind'] != kind: continue
            if term and term not in (record['inventory_no']+' '+record['model']).casefold(): continue
            self.assets[record['inventory_no']] = record
            self.assets_tree.insert('', 'end', iid=record['inventory_no'], values=(record['inventory_no'],record['model'],KINDS[record['kind']],record['room'],record['custodian'],CONDITIONS[record['condition']],money(record['cost_kopecks'])))

    def options(self, table):
        if table == 'models':
            data = app.rows(self.db, 'SELECT m.*,f.name AS manufacturer FROM models m JOIN manufacturers f ON f.id=m.manufacturer_id ORDER BY m.name')
            pairs = [(f"{r['name']} · {r['manufacturer']}", r['id']) for r in data]
        elif table == 'rooms':
            pairs = [(f"{r['code']} · {r['title']}",r['id']) for r in app.rows(self.db,'SELECT * FROM rooms ORDER BY code')]
        else:
            pairs = [(f"{r['name']} (№{r['id']})",r['id']) for r in app.rows(self.db,'SELECT * FROM '+table+' ORDER BY name')]
        if not pairs:
            raise ValueError('Нужный справочник пока пуст. Добавьте запись во вкладке «Справочники».')
        return dict(pairs)

    @staticmethod
    def label_for(options, key):
        return next((label for label,value in options.items() if value == key), '')

    def selected_asset(self):
        selected = self.assets_tree.selection()
        if not selected: raise ValueError('Сначала выберите строку оборудования.')
        return self.assets[selected[0]]

    def add_equipment(self):
        models, rooms, custodians = self.options('models'), self.options('rooms'), self.options('custodians')
        fields = [('number','Инвентарный номер',None,''),('model','Модель',models,''),('room','Кабинет',rooms,''),
                  ('custodian','Ответственное лицо',custodians,''),('cost','Стоимость, руб.',None,'0'),
                  ('condition','Состояние',{v:k for k,v in CONDITIONS.items()},'Исправно')]
        def save(d):
            if not d['number']: raise ValueError('Укажите инвентарный номер.')
            app.add_asset(self.db,d['number'],d['model'],d['room'],d['custodian'],rubles_to_kopecks(d['cost']),d['condition'])
            self.refresh();self.status.set(f"Добавлена карточка {d['number']}.")
        return EntryDialog(self,'Добавить оборудование',fields,save)

    def asset_details(self):
        r = self.selected_asset()
        return messagebox.showinfo('Карточка оборудования',
            f"Инвентарный номер: {r['inventory_no']}\nМодель: {r['model']}\nТип: {KINDS[r['kind']]}\nКабинет: {r['room']}\nОтветственный: {r['custodian']}\nСостояние: {CONDITIONS[r['condition']]}\nСтоимость: {money(r['cost_kopecks'])} ₽", parent=self)

    def move_equipment(self):
        record = self.selected_asset()
        if record['condition'] == 'written_off': raise ValueError('Списанное оборудование перемещать нельзя.')
        rooms = self.options('rooms')
        def save(d):
            app.move_asset(self.db,record['inventory_no'],d['room'],d['note'])
            self.refresh();self.status.set(f"Перемещение {record['inventory_no']} сохранено.")
        return EntryDialog(self,'Переместить '+record['inventory_no'],[
            ('room','Новый кабинет',rooms,self.label_for(rooms,record['room_id'])),('note','Примечание',None,'')],save)

    def refresh_inventory_list(self):
        previous = self.current_inventory()
        data = app.rows(self.db,'SELECT * FROM inventories ORDER BY id DESC')
        self.inventory_map = {f"№{r['id']} · {r['title']} · {'Открыта' if r['status']=='open' else 'Завершена'}":r['id'] for r in data}
        self.inventory_combo['values'] = list(self.inventory_map)
        self.inventory_var.set(self.label_for(self.inventory_map,previous) or next(iter(self.inventory_map),''))
        self.refresh_inventory()

    def current_inventory(self):
        return self.inventory_map.get(self.inventory_var.get())

    def refresh_inventory(self):
        self.clear(self.check_tree)
        key = self.current_inventory()
        self.inventory_rows = {}
        if key is None:
            self.check_summary.set('Проверок пока нет. Создайте первую кнопкой «Новая проверка».')
            self.inventory_status = None
        else:
            self.inventory_status = self.db.execute('SELECT status FROM inventories WHERE id=?',(key,)).fetchone()[0]
            data = app.report(self.db,key)
            pending = sum(r['presence']=='unchecked' for r in data)
            differences = sum(r['result'] not in ('совпадает','не проверено') for r in data)
            self.check_summary.set(f'Позиций: {len(data)}     Не проверено: {pending}     Расхождений: {differences}'+('     Проверка завершена, результаты сохранены.' if self.inventory_status=='closed' else ''))
            for r in data:
                self.inventory_rows[r['inventory_no']] = r
                tag = 'pending' if r['presence']=='unchecked' else 'warning' if r['result']!='совпадает' else ''
                self.check_tree.insert('', 'end', iid=r['inventory_no'],values=(r['inventory_no'],r['model'],r['expected_room'],r['observed_room'] or '—',PRESENCE[r['presence']],r['result'].capitalize()),tags=(tag,) if tag else ())
        state = 'normal' if self.inventory_status=='open' else 'disabled'
        for b in [self.found_button,self.missing_button,self.close_button]:b.configure(state=state)
        self.export_button.configure(state='normal' if key is not None else 'disabled')

    def new_inventory(self):
        def save(d):
            key = app.start_inventory(self.db,d['title'])
            self.refresh()
            self.inventory_var.set(self.label_for(self.inventory_map,key));self.refresh_inventory()
            self.status.set(f'Создана проверка №{key}. Выберите позицию и отметьте наличие.')
        return EntryDialog(self,'Новая инвентаризация',[('title','Название проверки',None,'Проверка оборудования')],save)

    def selected_check(self):
        if self.inventory_status!='open':raise ValueError('Для отметки выберите открытую проверку.')
        selected = self.check_tree.selection()
        if not selected:raise ValueError('Сначала выберите строку оборудования в проверке.')
        return self.inventory_rows[selected[0]]

    def mark_found(self):
        if self.inventory_status!='open': return
        r = self.selected_check();rooms = self.options('rooms')
        code = r['observed_room'] or r['expected_room']
        room_id = self.db.execute('SELECT id FROM rooms WHERE code=?',(code,)).fetchone()[0]
        condition = r['observed_condition'] or r['expected_condition']
        def save(d):
            app.mark_asset(self.db,self.current_inventory(),r['inventory_no'],'found',d['room'],d['condition'])
            self.refresh_inventory();self.status.set(f"{r['inventory_no']}: найдено. Результат сохранён.")
        return EntryDialog(self,'Найдено: '+r['inventory_no'],[
            ('room','Фактический кабинет',rooms,self.label_for(rooms,room_id)),
            ('condition','Фактическое состояние',{v:k for k,v in CONDITIONS.items()},CONDITIONS[condition])],save)

    def mark_missing(self):
        r = self.selected_check()
        app.mark_asset(self.db,self.current_inventory(),r['inventory_no'],'missing')
        self.refresh_inventory();self.status.set(f"{r['inventory_no']}: отсутствие зафиксировано.")

    def finish_inventory(self):
        key = self.current_inventory()
        if key is None:raise ValueError('Выберите проверку.')
        pending = sum(r['presence']=='unchecked' for r in self.inventory_rows.values())
        if pending:raise ValueError(f'Сначала проверьте оставшиеся позиции: {pending}.')
        if messagebox.askyesno('Завершить проверку?', 'После завершения результаты будут доступны для просмотра и выгрузки. Изменять их будет нельзя.',parent=self):
            app.close_inventory(self.db,key)
            self.refresh();self.status.set(f'Проверка №{key} завершена.')

    def export_inventory(self):
        key = self.current_inventory()
        if key is None:raise ValueError('Выберите проверку.')
        path = filedialog.asksaveasfilename(parent=self,title='Сохранить результаты',initialfile=f'Инвентаризация_{key}.csv',defaultextension='.csv',filetypes=[('Таблица CSV','*.csv')])
        if path:
            count = app.export_csv(self.db,key,Path(path))
            self.status.set(f'Сохранено строк: {count}. Файл: {Path(path).name}')

    def refresh_references(self):
        if self.db is None:return
        self.clear(self.refs_tree)
        kind = self.ref_kind.get();table = REFS[kind]
        if table=='models':
            data=app.rows(self.db,'SELECT m.*,f.name AS maker FROM models m JOIN manufacturers f ON f.id=m.manufacturer_id ORDER BY m.id')
            records=[(r['name'],f"{r['maker']} · {KINDS[r['kind']]}"+(f" · {r['ram_gb']} ГБ памяти" if r['ram_gb'] else '')) for r in data]
        else:
            data=app.rows(self.db,'SELECT * FROM '+table+' ORDER BY id')
            records=[(r['code'],r['title']) if table=='rooms' else (r['name'],'') for r in data]
        for row in records:self.refs_tree.insert('', 'end',values=row)

    def add_reference(self):
        table = REFS[self.ref_kind.get()]
        if table=='rooms':fields=[('code','Номер кабинета',None,''),('title','Название кабинета',None,'')]
        elif table=='models':
            fields=[('maker','Производитель',self.options('manufacturers'),''),('name','Название модели',None,''),
                    ('kind','Тип устройства',{v:k for k,v in KINDS.items()},'Компьютер'),
                    ('cpu','Частота процессора, МГц',None,''),('ram','Память, ГБ',None,''),
                    ('disk','Накопитель, ГБ',None,''),('screen','Экран, дюймы',None,''),
                    ('color','Цветная печать',{'Не применимо':None,'Нет':0,'Да':1},'Не применимо')]
        else:fields=[('name','Название' if table=='manufacturers' else 'ФИО или обозначение',None,'')]
        def save(d):
            with self.db:
                if table=='rooms':self.db.execute('INSERT INTO rooms(code,title) VALUES (?,?)',(d['code'],d['title']))
                elif table=='models':
                    def optional_int(v):
                        if not v:return None
                        try:n=int(v)
                        except ValueError:raise ValueError('Частота, память и накопитель задаются целыми числами.') from None
                        if n<=0:raise ValueError('Характеристики должны быть положительными.')
                        return n
                    try:screen=float(d['screen'].replace(',','.')) if d['screen'] else None
                    except ValueError:raise ValueError('Диагональ экрана задаётся числом.') from None
                    self.db.execute('INSERT INTO models(manufacturer_id,name,kind,cpu_mhz,ram_gb,disk_gb,screen_inch,color) VALUES (?,?,?,?,?,?,?,?)',
                        (d['maker'],d['name'],d['kind'],optional_int(d['cpu']),optional_int(d['ram']),optional_int(d['disk']),screen,d['color']))
                else:self.db.execute('INSERT INTO '+table+'(name) VALUES (?)',(d['name'],))
            self.refresh();self.status.set('Запись справочника сохранена.')
        return EntryDialog(self,'Добавить: '+self.ref_kind.get().lower(),fields,save)

    def refresh_history(self):
        self.clear(self.history_tree)
        for r in app.rows(self.db,'''SELECT a.inventory_no,r1.code AS from_room,r2.code AS to_room,m.moved_at,m.note
            FROM movements m JOIN assets a ON a.id=m.asset_id JOIN rooms r1 ON r1.id=m.from_room_id
            JOIN rooms r2 ON r2.id=m.to_room_id ORDER BY m.moved_at DESC,m.id DESC'''):
            try:stamp=datetime.fromisoformat(r['moved_at']).strftime('%d.%m.%Y %H:%M')
            except ValueError:stamp=r['moved_at']
            self.history_tree.insert('', 'end',values=(stamp,r['inventory_no'],r['from_room'],r['to_room'],r['note']))

    def close(self):
        if self.db is not None:self.db.close();self.db=None
        self.destroy()


def main():
    parser=argparse.ArgumentParser(description='Графический модуль инвентаризации')
    parser.add_argument('--db',type=Path,default=ROOT/'inventory.sqlite')
    args=parser.parse_args()
    window=InventoryWindow(args.db)
    if window.db is not None:window.mainloop()


if __name__=='__main__':main()
