# 本福丸訂製 — Engineering Agent Instructions

This repository powers the production website for 本福丸訂製.

- Repository: `ab0975548810-cloud/fan-phone`
- Production branch: `main`
- Production URL: `https://fanphone.zeabur.app`
- Deployment: pushes/merges to `main` trigger Zeabur

## Mandatory companion document

Before any substantial feature, architecture, POS, inventory, template, artwork, printer, or data-model work, read **`PROJECT_BLUEPRINT.md`** in the latest `main`.

- `AGENTS.md` = engineering rules, invariants, testing and current handoff.
- `PROJECT_BLUEPRINT.md` = product vision, target system architecture, module boundaries, production/printing roadmap and agreed long-term construction plan.

If current code conflicts with the blueprint, do not silently rewrite one side. Explain the conflict, risk and proposed migration/fix first.

## 1. Source of truth and working style

1. Before every change, fetch the latest `main` and inspect the current files. Never overwrite newer work with stale code.
2. Do not work directly on `main` for substantial changes. Use a feature branch and PR.
3. Keep changes scoped. Do not mix unrelated frontend, admin, AI, POS, inventory, template editor, or printer changes into one PR.
4. Prefer root-cause fixes over repeated one-off hotfix files. If the same subsystem keeps breaking, inspect its architecture and consolidate rather than stacking more patches.
5. Preserve existing working behavior. Do not remove or rewrite stable features unless the task explicitly requires it.
6. Commits should be clear and reversible.
7. If a request/tool operation times out, first re-read the latest branch/commit/check state before retrying. A previous write may already have succeeded.

## 2. Mandatory verification

For feature or bugfix PRs:

- Run the repository Smoke Test.
- Run the WebKit/browser regression where relevant.
- A green syntax/CI check does not prove browser behavior. For UI/editor/AI flows, verify the actual browser path when possible.
- Do not merge a PR with unexplained red checks.
- Before asking the user to test production, confirm the final `main` commit and Zeabur deployment are successful.

## 3. Frontend/editor invariants

The customer flow is QR scan → choose product → design phone case → submit order.

Keep these working:

- Fabric.js editor: upload, move, scale, rotate, adjust, flip, duplicate, bring forward, outline, delete, undo/redo, layers.
- AI background removal.
- Templates and asset/sticker flows.
- Production/high-resolution artwork generation.
- Main toolbar must remain directly usable while an object is selected.
- Object/history/layer/template controls must not cover the phone-case canvas, including iPad/Safari landscape layouts.
- Order submission must handle normal customer photo designs without failing because Fabric JSON embeds duplicate image Base64 data.

Important: the experimental "AI 大頭 / AI head cutout" feature was abandoned and removed from runtime. Do NOT re-enable old AI-head/MediaPipe scripts unless explicitly requested.

## 4. Admin invariants

Admin currently includes orders, brands/models, case materials/styles, asset library, template library/editor, plus performance/lazy-loading helpers.

- Do not break template editor lazy loading.
- AI background removal remains available in the admin template editor.
- Preserve order search behavior and order workflow logic.
- Do not assume old script names or old architecture are still current. Inspect latest files first.

## 5. Commerce / POS architecture

The backend should become a unified commerce/POS system, not a separate disconnected POS app.

Public product data may contain:

- brand/model
- case/material/style
- customer-facing sale price
- preview/product images

Private commerce data must contain/store:

- SKU
- cost price
- stock quantity
- low-stock threshold
- inventory tracking state
- order cost/profit snapshots
- future inventory transactions and reporting data

Never expose cost price, margin, profit, or private stock accounting through the public `/api/shop_data` API.

### SKU model

Use a stable SKU concept around product dimensions such as model + material/style + color/variant.

### Pricing and profit rules

- Admin can manage sale price and cost price.
- Calculate unit gross profit = sale price - cost price.
- Calculate gross margin when cost/sale data is known.
- At order creation, snapshot the actual sale price and cost used for that order.
- Later edits to current product price/cost must NOT change historical order profit.

### Inventory rules

- Tracked SKU stock decreases when an order is successfully created/reserved according to current business flow.
- Voiding an order must reverse the inventory effect exactly once.
- Restoring an order must re-apply the inventory effect exactly once.
- Prevent double deduction or double restoration on retries.
- Low-stock thresholds must be configurable.
- Inventory/accounting data must use persistent storage suitable for production; do not silently rely on ephemeral container filesystem state.

## 6. Order workflow

Current production workflow concept:

`待處理 → 製作中 → 待列印 → 列印中 → 已完成`

`作廢` remains a separate state/action.

Do not invent additional business states without a concrete requirement.

Orders will eventually connect to inventory and printer jobs, but printer-job state should remain sufficiently separate to prevent duplicate print dispatch.

## 7. Printer roadmap — do not implement prematurely

Future target:

Customer design → order → canonical high-resolution print artwork → print queue → vendor cloud-print API / 銳印 → A5 UV printer.

Vendor API documentation has already shown support for concepts including task creation, task IDs, start print, cancellation, callbacks, device/printer status, and stock/channel queries.

Before printer integration, print-ready specifications still need to be confirmed, including supported file formats, transparency, dimensions, DPI, RGB/CMYK/ICC, white ink/varnish/spot-color semantics, coordinate origin, and exact relationship with 銳印.

Do not embed vendor API secrets in frontend code or commit them. Secrets belong in server-side environment variables.

Use an idempotent print queue / unique print-job identity so retries cannot create duplicate physical prints.

## 8. Current handoff for Codex

Always fetch the latest production `main`; do not rely on a hard-coded commit SHA in handoff text.

There is already an in-progress POS implementation in:

- Branch: `backend-commerce-pos-v1-20260917`
- Pull request: `#8` — **POS Phase 1 — pricing, cost, profit and inventory core**

Do NOT start a second POS implementation from scratch.

### First task

1. Fetch latest `main`, read `PROJECT_BLUEPRINT.md`, and inspect PR #8 completely.
2. Bring the PR branch up to date with latest `main` before changing code.
3. Review the PR for architecture, security, persistence, idempotency, order-history correctness, and frontend/admin regressions.
4. Preserve the intended separation between public sale-price data and private cost/inventory/profit data.
5. Confirm the POS flow supports:
   - manage sale price
   - manage cost price
   - unit gross profit
   - gross margin
   - stock quantity
   - low-stock threshold
   - tracked/untracked stock
   - order sale/cost/profit snapshots
   - order creation stock deduction
   - void stock restoration
   - restore stock re-deduction
6. Fix any defects found on the existing PR branch instead of duplicating the implementation.
7. Run Smoke + WebKit/browser regression and explain any failure rather than bypassing it.
8. Do NOT merge to `main` automatically. Stop with a clean PR, test results, changed-file summary, risks/assumptions, and anything needing human/product approval.

## 9. Communication style for this project

The owner is not expected to understand framework/API jargon. Explain decisions in clear Traditional Chinese when reporting back. Be concise and practical: what changed, why, what was tested, what remains uncertain, and what needs approval.
