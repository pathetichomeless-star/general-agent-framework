# Public simulator financial invariants

The current quotation UI, scripted draft, synthetic fixtures and acceptance
path describe one product/quantity/price and one matching business line.
The entity diagram permits a 1–n relationship, but does not specify multi-line
pricing, allocation or header aggregation. This simulator therefore accepts
exactly one matching line for submission, approval and acceptance. Ambiguous
multi-line documents fail closed; no new multi-line pricing model is inferred.

- The unique active CNY `price_book_entry` for the active product is the
  quotation reference price. `product.list_price` and request `list_price`
  cannot replace that authority. A supplied reference must agree.
- A negotiated selling price is allowed. A supplied declared discount must
  agree with the cent-rounded selling price. Approval evaluates the effective
  reduction from catalog price to actual selling price, including cent rounding.
- Money uses decimal arithmetic to CNY cents. Exact half-cent midpoints are
  blocked pending the owner's choice of half-up versus half-even rounding.
  Other values use nearest-cent rounding (both rules agree). Selling
  prices must already be nonnegative cents. Quantity must be positive and finite.
  The backend financial JSON numeric DTO must round-trip without changing the validated decimal;
  unsupported precision is rejected. Policy comparison uses decimal numbers.
- Header product, quantity, price and currency must equal the business line.
  Total is calculated from that validated line. Supplied inconsistent totals
  are rejected. An incomplete draft may await its first line, but cannot submit,
  confirm or accept. Draft financial edits synchronize the existing line in the
  same SQLite transaction. Confirmed price changes require the owner and update
  both header and line atomically. Lines cannot independently diverge.
- Quotation submission/acceptance and order confirmation revalidate financial
  content. Approval effective inputs include product, catalog and line snapshots
  as applicable; changed dependencies invalidate pending decisions. No automatic
  repair, migration, approval recovery or historical financial rewrite occurs.

## Inventory monetary-risk blocker

The existing inventory/material model has no approved valuation source. Owner
decision for GAF-04C: do not invent unit costs, use client amounts, or assume zero.
With the application's configured monetary predicate, every cycle-count
adjustment fails before mutation until an owner-approved valuation model exists.
This includes small adjustments; it is an explicit compatibility restriction.

Quantity validation remains active: finite signed delta, nonnegative resulting
stock, magnitude `abs(delta) / stored_stock * 100`, and no guessed percentage at
zero stock. Client percentage claims must match; client monetary claims cannot
supply authority. Generic quantity/identity edits cannot replace the action.

An explicitly configured quantity-only policy can execute small adjustments or
require approval for large positive/negative movements. Tests use such policies
to retain lifecycle/role/atomicity coverage. Application policies and seed costs
are not changed. Inventory receipts remain a distinct existing business action;
this work does not redesign purchasing, stock initialization or valuation.

## Production workflow compatibility

Production creation and release require an authorized, confirmed sales order.
Material issue, progress and completion require the bound parent to remain in
production. New work orders carry a protected parent/content binding and
business-dependency versions. Pending, invalid or stale approvals cannot be
used to advance the parent. Expedited production and substitution use the
existing policy's independent approver; generic creation must use the business
action when approval is required.

Legacy work orders without a trusted binding fail closed. Parent or dependency
version changes, including parent notes or another work order's transition,
can invalidate an existing work order. There is no automatic migration,
rebinding, approval recovery or multi-work-order aggregation. Due-date and
note edits remain available, but a changed applicable policy can block further
execution. Release/completion can increment the work-order version twice;
clients must use the returned production reference or read the current record.

## Open findings and assurance scope

This is a synthetic public simulator, not a production-ready system or a
complete security certification. GAF-04/A/B/C/D regression results cover their
specified corrections; the interrupted independent review remains incomplete.
Private licensed Framework behavior has not been verified by these tests.

The following items remain open and were not remediated in this publication:

- GAF-01: UNKNOWN shipment projection.
- GAF-02: duplicate external dispatch.
- GAF-03: governed-action authorization.
- Inventory monetary valuation: no approved source; default cycle-count
  adjustments remain blocked before mutation.
- Exact half-cent rounding: pending an owner decision; midpoint inputs remain
  blocked, without choosing half-up or half-even semantics.
- Other interrupted-review findings: generic inventory creation can persist
  an invalid quantity; extreme-precision inventory movements can violate
  conservation; the scripted quotation draft can lose precision when converted
  to float; some non-production actions return an old record reference; staging
  seed installation can lose concurrent writes from another backend instance
  sharing the same SQLite file. The demo uses a single backend instance/lock;
  shared-instance installation safety is not established.

The review also left unverified suspicions and incomplete coverage. This list
does not claim that every equivalent path, deployment model or numeric boundary
has been audited. F1–F3 production lifecycle corrections do not close unrelated
findings.
