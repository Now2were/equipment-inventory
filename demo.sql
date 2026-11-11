-- Вымышленные учебные записи. Это не выгрузка имущества организации.
INSERT INTO manufacturers VALUES
    (1, 'Север'), (2, 'Вектор'), (3, 'Печать'), (4, 'Резерв');
INSERT INTO models VALUES
    (1, 1, 'Учебный ПК 16', 'PC', 3200, 16, 512, NULL, NULL),
    (2, 2, 'Ноутбук 8', 'Laptop', 2400, 8, 256, 15.6, NULL),
    (3, 3, 'Принтер Цвет', 'Printer', NULL, NULL, NULL, NULL, 1),
    (4, 1, 'Учебный ПК 8', 'PC', 2800, 8, 256, NULL, NULL),
    (5, 3, 'Принтер Моно', 'Printer', NULL, NULL, NULL, NULL, 0),
    (6, 2, 'Ноутбук 16', 'Laptop', 3000, 16, 512, 14, NULL);
INSERT INTO rooms VALUES
    (1, '101', 'Лаборатория А'), (2, '102', 'Лаборатория Б'),
    (3, '201', 'Мастерская'), (4, '202', 'Резервный кабинет');
INSERT INTO custodians VALUES (1, 'Ответственный А'), (2, 'Ответственный Б');
INSERT INTO assets VALUES
    (1, 'ИНВ-001', 1, 1, 1, 7000000, 'active'),
    (2, 'ИНВ-002', 1, 1, 1, 7000000, 'active'),
    (3, 'ИНВ-003', 2, 2, 2, 6000000, 'active'),
    (4, 'ИНВ-004', 3, 1, 1, 3500000, 'active'),
    (5, 'ИНВ-005', 4, 3, 2, 4000000, 'repair'),
    (6, 'ИНВ-006', 5, 2, 2, 2500000, 'active'),
    (7, 'ИНВ-007', 2, 3, 2, 6000000, 'active'),
    (8, 'ИНВ-008', 4, 3, 2, 0, 'written_off');
INSERT INTO inventories VALUES
    (1, 'Демонстрационная проверка', '2026-10-15T09:00:00+03:00', NULL, 'open');
INSERT INTO inventory_items (
    inventory_id, asset_id, expected_room_id, expected_custodian_id, expected_condition
)
SELECT 1, id, room_id, custodian_id, condition
FROM assets WHERE condition <> 'written_off';
UPDATE inventory_items SET presence = 'found', observed_room_id = expected_room_id,
    observed_condition = expected_condition, checked_at = '2026-10-15T10:00:00+03:00'
WHERE asset_id IN (1, 4, 7);
UPDATE inventory_items SET presence = 'found', observed_room_id = 2,
    observed_condition = 'active', checked_at = '2026-10-15T10:01:00+03:00'
WHERE asset_id = 2;
UPDATE inventory_items SET presence = 'missing', checked_at = '2026-10-15T10:02:00+03:00'
WHERE asset_id = 3;
UPDATE inventory_items SET presence = 'found', observed_room_id = 3,
    observed_condition = 'active', checked_at = '2026-10-15T10:03:00+03:00'
WHERE asset_id = 5;
INSERT INTO movements VALUES
    (1, 2, 1, 2, '2026-10-15T10:01:00+03:00', 'Демонстрационное перемещение');
UPDATE assets SET room_id = 2 WHERE id = 2;
