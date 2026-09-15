"""Fast pre-deploy smoke tests for the Benfuwan storefront/admin app.

This intentionally avoids external services. It catches broken Python imports,
missing frontend patch files, JavaScript syntax errors, and basic Flask route
regressions before a change is reported as ready.
"""
from pathlib import Path
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


# 4) Public/admin basic route checks without touching Runpod or Supabase.
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

print(f"SMOKE OK: {len(refs)} frontend scripts + Python middleware + core routes")
