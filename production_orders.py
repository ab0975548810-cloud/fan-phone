"""Production-only orders are keyed by immutable design revision, outside commerce."""
from order_designs import digest


def create(app, parent, revision, actor):
    key = 'MK-' + digest([parent, revision['version'], revision['content_hash']])[:32]
    record = dict(id=key, order_id=parent, version=revision['version'],
                  content_hash=revision['content_hash'], actor=actor)
    if app.USE_SUPABASE:
        app.SUPABASE.table('design_production_orders').upsert(
            record, on_conflict='id', ignore_duplicates=True).execute()
    else:
        with app.print_center.store.connection(True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS design_production_orders(
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL, version INTEGER NOT NULL,
                content_hash TEXT NOT NULL, actor TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(order_id, version))""")
            db.execute("""INSERT INTO design_production_orders
                (id,order_id,version,content_hash,actor) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING""", tuple(record.values()))
    return key

def lookup(app, key):
    if app.USE_SUPABASE:
        records = app.SUPABASE.table('design_production_orders').select('*').eq('id',key).limit(1).execute().data
        return records[0] if records else None
    with app.print_center.store.connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='design_production_orders'").fetchone():
            return None
        record = db.execute('SELECT * FROM design_production_orders WHERE id=?',(key,)).fetchone()
        return dict(record) if record else None


def starting_revision(app, root, rows, source):
    if not source:
        return rows[-1]
    record = lookup(app,source)
    if record and record['order_id']==root:
        for row in rows:
            if row['version']==record['version'] and row['content_hash']==record['content_hash']:
                return row
    raise ValueError('找不到此補印單的原始設計')
