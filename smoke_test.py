"""Fast pre-deploy smoke tests for the Benfuwan storefront/admin app.

This intentionally avoids external services. It catches broken Python imports,
missing frontend patch files, JavaScript syntax errors, core Flask route
regressions, order creation, and authenticated admin order listing before a
change is reported as ready.
"""
from pathlib import Path
import base64
import importlib
import os
import re
import subprocess
import sys

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


# 5) Create a real local test order through the same JSON endpoint the frontend uses.
# A valid 1x1 transparent PNG keeps the test tiny while exercising decoding,
# file persistence, shop lookup, price calculation, and response handling.
png_raw = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z7VQAAAAASUVORK5CYII="
)
png_url = "data:image/png;base64," + base64.b64encode(png_raw).decode("ascii")
model = app_module.DEFAULT_SHOP_DATA["models"][0]
style = app_module.DEFAULT_SHOP_DATA["styles"][0]
order_resp = client.post(
    "/api/create_order",
    json={
        "print_file": png_url,
        "mockup_file": png_url,
        "model_id": model["id"],
        "style_id": style["id"],
        "model_name": model["name"],
        "style_name": style["name"],
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


# 6) Log in and confirm the admin page and order API can read the created order.
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


# 7) Remove local smoke artifacts so CI leaves a clean workspace.
orders_dir = ROOT / "orders"
if orders_dir.exists():
    for path in list(orders_dir.iterdir()):
        if order_id in path.name:
            try:
                path.unlink()
            except Exception:
                pass

print(
    f"SMOKE OK: {len(refs)} frontend scripts + Python middleware + "
    "front routes + order creation + admin login/order listing"
)
