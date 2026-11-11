PRAGMA foreign_keys = ON;

CREATE TABLE manufacturers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
);
CREATE TABLE models (
    id INTEGER PRIMARY KEY,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    kind TEXT NOT NULL CHECK (kind IN ('PC', 'Laptop', 'Printer')),
    cpu_mhz INTEGER CHECK (cpu_mhz > 0),
    ram_gb INTEGER CHECK (ram_gb > 0),
    disk_gb INTEGER CHECK (disk_gb > 0),
    screen_inch REAL CHECK (screen_inch > 0),
    color INTEGER CHECK (color IN (0, 1)),
    UNIQUE (manufacturer_id, name)
);
CREATE TABLE rooms (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (length(trim(code)) > 0),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0)
);
CREATE TABLE custodians (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
);
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    inventory_no TEXT NOT NULL UNIQUE
        CHECK (length(trim(inventory_no)) > 0 AND inventory_no = trim(inventory_no)),
    model_id INTEGER NOT NULL REFERENCES models(id),
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    custodian_id INTEGER NOT NULL REFERENCES custodians(id),
    cost_kopecks INTEGER NOT NULL CHECK (typeof(cost_kopecks) = 'integer' AND cost_kopecks >= 0),
    condition TEXT NOT NULL CHECK (condition IN ('active', 'repair', 'written_off'))
);
CREATE TABLE inventories (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    started_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    CHECK ((status = 'open' AND closed_at IS NULL) OR
           (status = 'closed' AND closed_at IS NOT NULL))
);
CREATE TABLE inventory_items (
    inventory_id INTEGER NOT NULL REFERENCES inventories(id),
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    expected_room_id INTEGER NOT NULL REFERENCES rooms(id),
    expected_custodian_id INTEGER NOT NULL REFERENCES custodians(id),
    expected_condition TEXT NOT NULL CHECK (expected_condition IN ('active', 'repair')),
    observed_room_id INTEGER REFERENCES rooms(id),
    observed_condition TEXT CHECK (observed_condition IN ('active', 'repair', 'written_off')),
    presence TEXT NOT NULL DEFAULT 'unchecked'
        CHECK (presence IN ('unchecked', 'found', 'missing')),
    checked_at TEXT,
    PRIMARY KEY (inventory_id, asset_id),
    CHECK ((presence = 'unchecked' AND observed_room_id IS NULL
                AND observed_condition IS NULL AND checked_at IS NULL) OR
           (presence = 'missing' AND observed_room_id IS NULL
                AND observed_condition IS NULL AND checked_at IS NOT NULL) OR
           (presence = 'found' AND observed_room_id IS NOT NULL
                AND observed_condition IS NOT NULL AND checked_at IS NOT NULL))
);
CREATE TABLE movements (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    from_room_id INTEGER NOT NULL REFERENCES rooms(id),
    to_room_id INTEGER NOT NULL REFERENCES rooms(id),
    moved_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    CHECK (from_room_id <> to_room_id)
);
CREATE INDEX idx_assets_room ON assets(room_id);
CREATE INDEX idx_assets_model ON assets(model_id);
CREATE INDEX idx_items_presence ON inventory_items(inventory_id, presence);
CREATE INDEX idx_movements_latest ON movements(asset_id, moved_at DESC, id DESC);

CREATE TRIGGER inventory_items_closed_update BEFORE UPDATE ON inventory_items
WHEN (SELECT status FROM inventories WHERE id = OLD.inventory_id) = 'closed'
  OR (SELECT status FROM inventories WHERE id = NEW.inventory_id) = 'closed'
BEGIN SELECT RAISE(ABORT, 'closed inventory'); END;
CREATE TRIGGER inventory_items_closed_insert BEFORE INSERT ON inventory_items
WHEN (SELECT status FROM inventories WHERE id = NEW.inventory_id) = 'closed'
BEGIN SELECT RAISE(ABORT, 'closed inventory'); END;
CREATE TRIGGER inventory_items_closed_delete BEFORE DELETE ON inventory_items
WHEN (SELECT status FROM inventories WHERE id = OLD.inventory_id) = 'closed'
BEGIN SELECT RAISE(ABORT, 'closed inventory'); END;
CREATE TRIGGER inventories_closed_update BEFORE UPDATE ON inventories
WHEN OLD.status = 'closed'
BEGIN SELECT RAISE(ABORT, 'closed inventory'); END;
CREATE TRIGGER inventories_close_unchecked BEFORE UPDATE OF status ON inventories
WHEN NEW.status = 'closed' AND EXISTS (
    SELECT 1 FROM inventory_items WHERE inventory_id = OLD.id AND presence = 'unchecked'
)
BEGIN SELECT RAISE(ABORT, 'unchecked inventory items'); END;
