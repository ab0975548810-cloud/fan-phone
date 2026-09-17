"""Fast pre-deploy smoke tests for the Benfuwan storefront/admin app.

This intentionally avoids external services. It catches broken Python imports,
missing frontend patch files, JavaScript syntax errors, core Flask route
regressions, order creation, authenticated admin order listing, production
workflow, and the private POS cost/stock/profit lifecycle before deployment.
"""
from pathlib import Path
import base64
import importlib
import os
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)


def fail(msg):
    raise SystemExit(f"SMOKE FAIL: {msg}")


# 1) Python syntax for every project module.
for path in sorted(ROOT.glob("*.py")):
    if path.name == "smoke_test.py":
        continue
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        fail(f"Python syntax: {path.name}\n{proc.stderr}")


# 2) Every JS patch injected by index.html must exist and parse in Node.
index = (ROOT / "index.html").read_text(encoding="utf-8")
refs = sorted(set(re.findall(r'/static/([^\"?]+\.js)', index)))
if not refs:
    fail("index.html does not reference any frontend JS patches")
for rel in refs:
    path = ROOT / "static" / rel
    if not path.exists():
        fail(f"Missing frontend patch: static/{rel}")
    proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    if proc.returncode:
        fail(f"JavaScript syntax: static/{rel}\n{proc.stderr}")

for admin_js in ("admin-orders-v3.js", "admin-commerce-v1.js"):
    path = ROOT / "static" / admin_js
    if not path.exists():
        fail(f"Missing admin module: static/{admin_js}")
    proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    if proc.returncode:
        fail(f"JavaScript syntax: static/{admin_js}\n{proc.stderr}")


test_dir = tempfile.TemporaryDirectory()
os.environ['COMMERCE_DB_PATH'] = str(Path(test_dir.name) / 'commerce.sqlite3')
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)

# 3) Import Flask app and install the exact production middleware set.
app_module = importlib.import_module("app")
installers = [
    ("security_perf", "install"),
    ("supabase_resilience", "install"),
    ("quality_perf_patch", "install"),
    ("ai_runtime_patch", "install"),
    ("admin_perf_patch", "install"),
    ("order_color_patch", "install"),
    ("asset_category_patch", "install"),
    ("template_editor_patch", "install"),
    ("order_management_patch", "install"),
    ("commerce_patch", "install"),
]
for module_name, fn_name in installers:
    module = importlib.import_module(module_name)
    getattr(module, fn_name)(app_module)


# 4) Public route checks without touching Runpod or Supabase.
client = app_module.app.test_client()
checks = [
    ("/", {200}),
    ("/api/health", {200}),
    ("/login", {200}),
    ("/admin", {301, 302, 303, 307, 308}),
]
for url, expected in checks:
    response = client.get(url, follow_redirects=False)
    if response.status_code not in expected:
        fail(f"GET {url}: HTTP {response.status_code}, expected {sorted(expected)}")


# 5) Log in and initialize private POS inventory before creating the order.
login_resp = client.post(
    "/login",
    data={"password": app_module.ADMIN_PASSWORD},
    follow_redirects=False,
)
if login_resp.status_code not in {301, 302, 303, 307, 308}:
    fail(f"POST /login: HTTP {login_resp.status_code}")
admin_resp = client.get("/admin", follow_redirects=False)
if admin_resp.status_code != 200:
    fail(f"Authenticated GET /admin: HTTP {admin_resp.status_code}")
if b"admin-orders-v3.js" not in admin_resp.data:
    fail("Authenticated /admin did not inject admin-orders-v3.js")
if b"admin-commerce-v1.js" not in admin_resp.data:
    fail("Authenticated /admin did not inject admin-commerce-v1.js")

sync_resp = client.post("/api/admin/commerce_sync_skus")
sync_json = sync_resp.get_json() or {}
if sync_resp.status_code != 200 or sync_json.get("status") != "success":
    fail(f"POST /api/admin/commerce_sync_skus: {sync_resp.status_code} {sync_resp.get_data(as_text=True)[:400]}")

commerce_resp = client.get("/api/admin/commerce_data")
commerce_json = commerce_resp.get_json() or {}
if commerce_resp.status_code != 200 or commerce_json.get("status") != "success":
    fail(f"GET /api/admin/commerce_data: {commerce_resp.status_code}")
commerce = commerce_json.get("data") or {}
model = app_module.DEFAULT_SHOP_DATA["models"][0]
style = app_module.DEFAULT_SHOP_DATA["styles"][0]
sku = next((s for s in commerce.get("skus") or [] if s.get("model_id") == model["id"] and s.get("style_id") == style["id"] and s.get("color") == "透明"), None)
if not sku:
    fail("POS sync did not create the expected model/style/color SKU")
sku["cost_price"] = 100
sku["stock_qty"] = 5
sku["low_stock_threshold"] = 2
sku["track_stock"] = True
save_commerce = client.post(
    "/api/admin/save_commerce_data",
    json={"revision": commerce["revision"], "style_defaults": commerce.get("style_defaults") or {}, "skus": commerce.get("skus") or []},
)
if save_commerce.status_code != 200:
    fail(f"POST /api/admin/save_commerce_data: {save_commerce.status_code} {save_commerce.get_data(as_text=True)[:400]}")


# 6) Create a real local test order through the same JSON endpoint the frontend uses.
png_raw = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z7VQAAAAASUVORK5CYII="
)
png_url = "data:image/png;base64," + base64.b64encode(png_raw).decode("ascii")
order_resp = client.post(
    "/api/create_order",
    json={
        "idempotency_key": "smoke-order-00000001",
        "print_file": png_url,
        "mockup_file": png_url,
        "model_id": model["id"],
        "style_id": style["id"],
        "model_name": model["name"],
        "style_name": style["name"],
        "color_name": "透明",
        "quantity": 1,
        "customer_name": "測試先生",
        "payment_method": "現金",
        "design_json": {"smoke": True},
    },
)
try:
    order_json = order_resp.get_json() or {}
except Exception:
    order_json = {}
if order_resp.status_code != 200 or order_json.get("status") != "success":
    fail(f"POST /api/create_order: HTTP {order_resp.status_code}, body={order_resp.get_data(as_text=True)[:500]}")
order_id = str(order_json.get("order_id") or "")
if not order_id:
    fail("POST /api/create_order returned no order_id")

# POS snapshot must lock cost/profit and deduct tracked stock exactly once.
commerce_after = (client.get("/api/admin/commerce_data").get_json() or {})
sku_after = next((s for s in (commerce_after.get("data") or {}).get("skus") or [] if s.get("id") == sku.get("id")), None)
if not sku_after or sku_after.get("stock_qty") != 4:
    fail(f"POS stock was not deducted from 5 to 4: {sku_after}")
pos_summary = commerce_after.get("summary") or {}
expected_profit = int(style["price"]) - 100
if round(float(pos_summary.get("gross_profit") or 0)) != expected_profit:
    fail(f"POS gross profit snapshot mismatch: {pos_summary}")


# 7) Confirm admin order API can read the created order.
orders_resp = client.get("/api/admin/get_orders?limit=10")
try:
    orders_json = orders_resp.get_json() or {}
except Exception:
    orders_json = {}
if orders_resp.status_code != 200 or orders_json.get("status") != "success":
    fail(f"GET /api/admin/get_orders: HTTP {orders_resp.status_code}, body={orders_resp.get_data(as_text=True)[:500]}")
rows = orders_json.get("data") or []
if not any(str(row.get("order_id") or row.get("id") or "") == order_id for row in rows):
    fail("Admin order list did not include the just-created smoke order")


# 8) Exercise void/restore stock reversal, then guarded production workflow.
void_resp = client.post("/api/admin/order_action", json={"idempotency_key": uuid.uuid4().hex, "order_id": order_id, "action": "void"})
if void_resp.status_code != 200:
    fail(f"Void order failed: {void_resp.status_code} {void_resp.get_data(as_text=True)[:300]}")
void_data = client.get("/api/admin/commerce_data").get_json() or {}
void_sku = next((s for s in (void_data.get("data") or {}).get("skus") or [] if s.get("id") == sku.get("id")), None)
if not void_sku or void_sku.get("stock_qty") != 5:
    fail(f"Voiding order did not restore stock to 5: {void_sku}")

restore_resp = client.post("/api/admin/order_action", json={"idempotency_key": uuid.uuid4().hex, "order_id": order_id, "action": "restore"})
if restore_resp.status_code != 200:
    fail(f"Restore order failed: {restore_resp.status_code} {restore_resp.get_data(as_text=True)[:300]}")
restore_data = client.get("/api/admin/commerce_data").get_json() or {}
restore_sku = next((s for s in (restore_data.get("data") or {}).get("skus") or [] if s.get("id") == sku.get("id")), None)
if not restore_sku or restore_sku.get("stock_qty") != 4:
    fail(f"Restoring order did not deduct stock back to 4: {restore_sku}")

for new_status in ("製作中", "待列印"):
    status_resp = client.post(
        "/api/admin/order_action",
        json={"idempotency_key": uuid.uuid4().hex, "order_id": order_id, "action": "set_status", "new_status": new_status},
    )
    status_json = status_resp.get_json() or {}
    if status_resp.status_code != 200 or status_json.get("new_status") != new_status:
        fail(
            f"Order status -> {new_status}: HTTP {status_resp.status_code}, "
            f"body={status_resp.get_data(as_text=True)[:500]}"
        )

orders_resp = client.get("/api/admin/get_orders?limit=10")
rows = (orders_resp.get_json() or {}).get("data") or []
row = next((r for r in rows if str(r.get("order_id") or r.get("id") or "") == order_id), None)
if not row or row.get("status") != "待列印":
    fail("Admin order list did not persist the production workflow status")

invalid_resp = client.post(
    "/api/admin/order_action",
    json={"idempotency_key": uuid.uuid4().hex, "order_id": order_id, "action": "set_status", "new_status": "亂填狀態"},
)
if invalid_resp.status_code != 400:
    fail(f"Invalid order status was not rejected: HTTP {invalid_resp.status_code}")


# 9) Remove local smoke artifacts so CI leaves a clean workspace.
orders_dir = ROOT / "orders"
if orders_dir.exists():
    for path in list(orders_dir.iterdir()):
        if order_id in path.name:
            try:
                path.unlink()
            except Exception:
                pass
commerce_file = ROOT / "commerce_data.json"
if commerce_file.exists():
    try:
        commerce_file.unlink()
    except Exception:
        pass

print(
    f"SMOKE OK: {len(refs)} frontend scripts + admin order/POS modules + Python middleware + "
    "front routes + POS SKU/cost/stock/profit + order creation + admin workflow"
)
