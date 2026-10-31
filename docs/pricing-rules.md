# Pricing rules of Medusa 2.22.2 — the oracle's specification

The oracle (`src/shop_api/oracle/`) implements the rules below **independently** of Medusa's code.
Sources: Medusa documentation (links) and measurements on the pinned stand (2026-10-31), recorded in
the scenario file `data/calculations/scenarios.yaml`. Where documentation and behaviour could differ,
the scenario decides, and the decision is listed under "Ambiguous rules".

## Vocabulary

| Term | Meaning |
|---|---|
| unit price | Price of one unit in the cart's currency as configured (may include tax) |
| net | Amount without tax |
| item_subtotal | Σ net line amounts before discounts |
| discount_total | Σ discounts **including the tax on them** (gross), plus shipping discounts |
| total | item_total + shipping_total, where item_total = discounted net × (1 + tax rate) |

## Rules

### 1. Promotion types and methods
- `standard` and `buyget` promotions; method `percentage` (0–100) or `fixed` (amount in the promotion's
  currency). [Application method](https://docs.medusajs.com/resources/commerce-modules/promotion/application-method)
- A `currency_code` on the application method restricts the promotion to carts in that currency; a
  mismatch gives **no discount and no error** (measured: EUR code on a USD cart is accepted, discount 0).

### 2. Targets and allocation
| target_type | allocation | Rule |
|---|---|---|
| `order` | `across` | Percentage of each line's net amount; a fixed amount is split across lines **in proportion to their net amounts** (3.33 + 9.99 with 10 off → 2.50 + 7.50) |
| `items` | `across` | As above, but only lines that match `target_rules` |
| `items` | `each` | Per matching line: per-unit discount × min(quantity, `max_quantity`); `max_quantity` is **required** |
| `items` | `once` | `max_quantity` units in total, **cheapest units first**, may spill into the next line |
| `shipping_methods` | `across` | Percentage or fixed amount off the shipping method |

A fixed discount never exceeds what it applies to: 50 off a 9.99 cart gives 9.99 and total 0.

### 3. Buy X get Y
The "buy" condition is `buy_rules_min_quantity` units of products matching `buy_rules`. Up to
`apply_to_quantity` units of products matching `target_rules` are discounted, **highest unit price first**.
The target must already be in the cart. [Docs](https://docs.medusajs.com/resources/commerce-modules/promotion/application-method#buy-promotion-rules)

### 4. Conditions
- Cart rules: `region.id`, `currency_code`, `customer.groups.id`, `shipping_address.country_code`,
  `sales_channel_id`, and numeric rules on cart totals with `gte`/`lte`/`gt`/`lt`, e.g.
  `item_subtotal gte 20`. [Rule attributes](https://docs.medusajs.com/resources/commerce-modules/promotion/concepts#rule-attributes)
- The threshold is **inclusive** for `gte` and compared against the subtotal **before** discounts
  (measured: 19.99 → no discount, 20.00 and 20.01 → discount).

### 5. Stacking
Several codes on one cart are all applied, and they **do not compound**: each percentage is computed on
the undiscounted net amounts, so the order of codes does not matter (measured: 10 % + 5.00 off on 25.00
→ 7.50 off, in both orders).

### 6. Taxes
- Tax is computed on the **discounted** net amount: `item_tax = (net − discounts) × rate`.
- **Tax-exclusive prices:** net = price. **Tax-inclusive prices:** net = price ÷ (1 + rate). A price is
  tax-inclusive when the price preference of its scope says so — a *currency* price follows the currency's
  preference, a *region-scoped* price follows the region's preference (measured; the scenarios use
  region-scoped prices so the shared EUR preference is never touched).
  [Tax-inclusive pricing](https://docs.medusajs.com/resources/commerce-modules/pricing/tax-inclusive-pricing)
- **Tax-inclusive promotions** (`is_tax_inclusive: true`): a fixed amount is reduced by the tax first:
  10 ÷ 1.25 = 8 net. [Tax-inclusive promotions](https://docs.medusajs.com/resources/commerce-modules/promotion/promotion-taxes)

Documentation examples reproduced exactly (25 % tax, 100 cart, 10 off): tax-exclusive promotion →
**112.50**; tax-inclusive promotion → **115**; tax-inclusive promotion with tax-inclusive prices → **90**.

### 7. Precision and rounding
- Medusa keeps **full precision** and does not round to the currency's minor unit at any step:
  15 % off 3 × 9.99 is 4.4955 and the cart total 25.4745 EUR; 33 % off 0.01 leaves 0.0067 EUR.
- The oracle therefore computes exactly with `Decimal` (34 digits) and compares with Medusa within
  1e-9. Medusa reports up to 20 significant digits.
- This project's **own** rounding policy for chargeable amounts is half-up to the minor unit
  (`to_minor_units`: EUR/USD 2, JPY 0, KWD 3 decimals). Under that policy an unrounded payment amount
  is a defect: see BUG-API-006.

## Ambiguous rules (decided by measurement, open questions for the product owner)

| Topic | Observed | Question |
|---|---|---|
| Money precision | Totals, order totals and payment collection amounts carry sub-cent values (35.4745 EUR) | Who rounds, and when? A card processor charges whole cents, so the books and the payment can disagree by up to half a cent per order → BUG-API-006 |
| Currency mismatch | Code accepted, discount 0, no message | Should the API reject the code so the shopper knows it does not apply? |
| Stacking | All codes apply, non-compounding | Is stacking intended by default, or should codes be exclusive unless configured? |

## Discrepancy log (stage 1.10)

| Discrepancy | Classification | Resolution |
|---|---|---|
| Property test: discount 2.740…001 > original 2.74 with 7.5 % tax-inclusive prices | **Oracle error** (precision noise after ÷ then × (1 + rate)) | Comparisons use a 1e-20 tolerance |
| Tax-inclusive price preference on the region had no effect on currency prices | **Oracle/test assumption** corrected against the docs | Scenarios use region-scoped prices |
| Payment amount 35.4745 EUR | **Product defect** under this project's rounding policy (ambiguous in Medusa's docs) | BUG-API-006, strict xfail |
| All 40 scenarios | API = oracle within 1e-9 | — |
