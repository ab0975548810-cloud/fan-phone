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
