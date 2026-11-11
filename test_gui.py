"""Испытания форм GUI на отдельной временной базе."""
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
import gui


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'gui.sqlite'
        app.initialize(self.path,demo=True)
        self.ui = gui.InventoryWindow(self.path)
        self.ui.withdraw()
        self.ui.update_idletasks()

    def tearDown(self):
        self.ui.close()
        self.temp.cleanup()

    def test_initial_display_and_filters(self):
        self.assertEqual(len(self.ui.assets_tree.get_children()),8)
        self.assertEqual(len(self.ui.check_tree.get_children()),7)
        self.assertIn('Не проверено: 1',self.ui.check_summary.get())
        self.ui.kind.set('Компьютер')
        self.assertEqual(len(self.ui.assets_tree.get_children()),4)
        self.ui.search.set('ИНВ-001')
        self.assertEqual(self.ui.assets_tree.get_children(),('ИНВ-001',))

    def test_asset_form_decimal_and_duplicate(self):
        dialog=self.ui.add_equipment()
        dialog.variables['number'].set('ТЕСТ-009')
        dialog.variables['cost'].set('12345,67')
        dialog.save()
        self.assertEqual(self.ui.db.execute("SELECT cost_kopecks FROM assets WHERE inventory_no='ТЕСТ-009'").fetchone()[0],1234567)
        self.assertIn('ТЕСТ-009',self.ui.assets_tree.get_children())
        dialog=self.ui.add_equipment()
        dialog.variables['number'].set('ТЕСТ-009')
        with patch('gui.messagebox.showerror') as error:
            dialog.save()
        self.assertTrue(error.called)
        self.assertTrue(dialog.winfo_exists())
        dialog.destroy()

    def test_move_form_records_history(self):
        self.ui.assets_tree.selection_set('ИНВ-001')
        dialog=self.ui.move_equipment()
        dialog.variables['room'].set(self.ui.label_for(self.ui.options('rooms'),3))
        dialog.variables['note'].set('Испытание формы')
        dialog.save()
        self.assertEqual(self.ui.db.execute('SELECT room_id FROM assets WHERE id=1').fetchone()[0],3)
        self.assertEqual(len(self.ui.history_tree.get_children()),2)

    def test_check_form_finish_and_export(self):
        self.ui.check_tree.selection_set('ИНВ-006')
        dialog=self.ui.mark_found()
        dialog.save()
        self.assertIn('Не проверено: 0',self.ui.check_summary.get())
        with patch('gui.messagebox.askyesno',return_value=True):
            self.ui.finish_inventory()
        self.assertEqual(self.ui.inventory_status,'closed')
        self.assertEqual(str(self.ui.found_button['state']),'disabled')
        output=Path(self.temp.name)/'export.csv'
        with patch('gui.filedialog.asksaveasfilename',return_value=str(output)):
            self.ui.export_inventory()
        with output.open(encoding='utf-8-sig',newline='') as f:
            self.assertEqual(len(list(csv.DictReader(f,delimiter=';'))),7)

    def test_missing_and_pending_close(self):
        self.ui.check_tree.selection_set('ИНВ-006')
        self.ui.mark_missing()
        self.assertEqual(self.ui.inventory_rows['ИНВ-006']['presence'],'missing')
        # Новая проверка содержит все семь позиций в состоянии unchecked.
        d=self.ui.new_inventory();d.variables['title'].set('Проверка формы');d.save()
        self.assertEqual(self.ui.current_inventory(),2)
        with self.assertRaisesRegex(ValueError,'оставшиеся позиции'):
            self.ui.finish_inventory()

    def test_reference_form(self):
        self.ui.ref_kind.set('Кабинеты')
        d=self.ui.add_reference()
        d.variables['code'].set('303');d.variables['title'].set('Учебный кабинет');d.save()
        self.assertEqual(self.ui.db.execute("SELECT title FROM rooms WHERE code='303'").fetchone()[0],'Учебный кабинет')

    def test_invalid_database_keeps_current(self):
        other=Path(self.temp.name)/'other.sqlite'
        import sqlite3
        sqlite3.connect(other).close()
        with self.assertRaises(ValueError):self.ui.use_database(other)
        self.assertEqual(self.ui.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],8)


class MoneyTests(unittest.TestCase):
    def test_money_exact(self):
        self.assertEqual(gui.rubles_to_kopecks('75 000,50'),7500050)
        self.assertEqual(gui.rubles_to_kopecks('0'),0)
        for value in ['NaN','Infinity','-1','0.001','не число']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                gui.rubles_to_kopecks(value)


if __name__=='__main__':unittest.main(verbosity=2)
