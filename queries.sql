-- Q01 Компьютеры с оперативной памятью от заданного объёма
SELECT a.inventory_no, m.name, m.ram_gb
FROM assets a JOIN models m ON m.id = a.model_id
WHERE m.kind = 'PC' AND m.ram_gb >= :min_ram
  AND a.condition <> 'written_off'
ORDER BY a.inventory_no;

-- Q02 Производители моделей принтеров
SELECT DISTINCT f.name
FROM manufacturers f JOIN models m ON m.manufacturer_id = f.id
WHERE m.kind = 'Printer'
ORDER BY f.name;

-- Q03 Ноутбуки стоимостью от заданной суммы копеек
SELECT a.inventory_no, m.name, m.ram_gb, m.screen_inch,
       a.cost_kopecks / 100.0 AS cost_rub
FROM assets a JOIN models m ON m.id = a.model_id
WHERE m.kind = 'Laptop' AND a.cost_kopecks >= :min_cost
  AND a.condition <> 'written_off'
ORDER BY a.inventory_no;

-- Q04 Цветные принтеры на учёте
SELECT a.inventory_no, m.name
FROM assets a JOIN models m ON m.id = a.model_id
WHERE m.kind = 'Printer' AND m.color = 1
  AND a.condition <> 'written_off'
ORDER BY a.inventory_no;

-- Q05 Производители и частоты моделей ноутбуков с подходящим диском
SELECT DISTINCT f.name, m.cpu_mhz
FROM manufacturers f JOIN models m ON m.manufacturer_id = f.id
WHERE m.kind = 'Laptop' AND m.disk_gb >= :min_disk
ORDER BY f.name, m.cpu_mhz;

-- Q06 Учёт оборудования выбранного производителя
SELECT a.inventory_no, m.kind, m.name, a.cost_kopecks / 100.0 AS cost_rub
FROM assets a JOIN models m ON m.id = a.model_id
JOIN manufacturers f ON f.id = m.manufacturer_id
WHERE f.name = :manufacturer AND a.condition <> 'written_off'
ORDER BY a.inventory_no;

-- Q07 Производители моделей ПК без моделей ноутбуков
SELECT f.name FROM manufacturers f
WHERE EXISTS (SELECT 1 FROM models m
              WHERE m.manufacturer_id = f.id AND m.kind = 'PC')
  AND NOT EXISTS (SELECT 1 FROM models m
                  WHERE m.manufacturer_id = f.id AND m.kind = 'Laptop')
ORDER BY f.name;

-- Q08 Самые дорогие принтеры с сохранением равных максимумов
SELECT a.inventory_no, m.name, a.cost_kopecks / 100.0 AS cost_rub
FROM assets a JOIN models m ON m.id = a.model_id
WHERE m.kind = 'Printer' AND a.condition <> 'written_off'
  AND a.cost_kopecks = (
    SELECT MAX(a2.cost_kopecks)
    FROM assets a2 JOIN models m2 ON m2.id = a2.model_id
    WHERE m2.kind = 'Printer' AND a2.condition <> 'written_off'
  )
ORDER BY a.inventory_no;

-- Q09 Средняя стоимость несписанной техники в рублях
SELECT ROUND(AVG(cost_kopecks) / 100.0, 2) AS average_rub
FROM assets WHERE condition <> 'written_off';

-- Q10 Несписанное оборудование по кабинетам включая пустые
SELECT r.code, COUNT(a.id) AS asset_count
FROM rooms r LEFT JOIN assets a
  ON a.room_id = r.id AND a.condition <> 'written_off'
GROUP BY r.id, r.code
ORDER BY r.code;

-- Q11 Кабинеты с количеством оборудования не ниже порога
SELECT r.code, COUNT(a.id) AS asset_count
FROM rooms r JOIN assets a ON a.room_id = r.id
WHERE a.condition <> 'written_off'
GROUP BY r.id, r.code
HAVING COUNT(a.id) >= :min_count
ORDER BY r.code;

-- Q12 Доля каждого типа включая нулевые значения
WITH kinds(kind) AS (VALUES ('PC'), ('Laptop'), ('Printer')),
counts AS (
    SELECT m.kind, COUNT(*) AS n
    FROM assets a JOIN models m ON m.id = a.model_id
    WHERE a.condition <> 'written_off'
    GROUP BY m.kind
)
SELECT k.kind, COALESCE(c.n, 0) AS asset_count,
       COALESCE(ROUND(100.0 * COALESCE(c.n, 0) /
         NULLIF((SELECT SUM(n) FROM counts), 0), 2), 0.0) AS share_percent
FROM kinds k LEFT JOIN counts c ON c.kind = k.kind
ORDER BY k.kind;

-- Q13 Производители с максимальным и минимальным количеством единиц
WITH counts AS (
    SELECT f.id, f.name, COUNT(a.id) AS n
    FROM manufacturers f LEFT JOIN models m ON m.manufacturer_id = f.id
    LEFT JOIN assets a ON a.model_id = m.id AND a.condition <> 'written_off'
    GROUP BY f.id, f.name
)
SELECT name, n FROM counts
WHERE n = (SELECT MIN(n) FROM counts) OR n = (SELECT MAX(n) FROM counts)
ORDER BY name;

-- Q14 Расхождения относительно снимка начала проверки
SELECT a.inventory_no, i.presence,
       CASE WHEN i.presence = 'missing' THEN 1 ELSE 0 END AS missing,
       CASE WHEN i.presence = 'found' AND i.expected_room_id <> i.observed_room_id
            THEN 1 ELSE 0 END AS room_changed,
       CASE WHEN i.presence = 'found' AND i.expected_condition <> i.observed_condition
            THEN 1 ELSE 0 END AS condition_changed
FROM inventory_items i JOIN assets a ON a.id = i.asset_id
WHERE i.inventory_id = :inventory_id
  AND (i.presence = 'missing' OR
       (i.presence = 'found' AND
        (i.expected_room_id <> i.observed_room_id OR
         i.expected_condition <> i.observed_condition)))
ORDER BY a.inventory_no;

-- Q15 Ещё не проверенные позиции
SELECT a.inventory_no, r.code AS expected_room
FROM inventory_items i JOIN assets a ON a.id = i.asset_id
JOIN rooms r ON r.id = i.expected_room_id
WHERE i.inventory_id = :inventory_id AND i.presence = 'unchecked'
ORDER BY a.inventory_no;

-- Q16 Последнее перемещение каждой единицы
WITH ranked AS (
    SELECT asset_id, from_room_id, to_room_id, moved_at,
           ROW_NUMBER() OVER (
             PARTITION BY asset_id ORDER BY moved_at DESC, id DESC
           ) AS rn
    FROM movements
)
SELECT a.inventory_no, r1.code AS from_room, r2.code AS to_room, x.moved_at
FROM ranked x JOIN assets a ON a.id = x.asset_id
JOIN rooms r1 ON r1.id = x.from_room_id
JOIN rooms r2 ON r2.id = x.to_room_id
WHERE x.rn = 1
ORDER BY a.inventory_no;
