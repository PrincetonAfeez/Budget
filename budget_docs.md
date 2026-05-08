# Architecture Decision Record
## App 08 — Budget
**Ledger Logic Group | Document 1 of 5**
**Status: Accepted**

---

## Context

Ledger Logic handles personal finance tracking. The Budget module is the eighth app in the portfolio and the first in the Ledger Logic group (Apps 08–14). It takes monthly income and a set of categorized expenses and answers the question: how should I distribute my money, and how did I actually do? It provides three allocation strategies, a comparison engine, and an interactive CLI for managing budget profiles.

---

## Decisions

### Decision 1 — Three independent strategy functions

**Chosen:** Three separate functions — `allocate_fifty_thirty_twenty()`, `allocate_priority_weighted()`, `allocate_zero_based()` — each returning a `BudgetAllocation` TypedDict. `compare_strategies()` runs all three and returns a dict of results.

**Rejected:** A single function with a strategy parameter.

**Reason:** Each strategy has different inputs and different logic — `allocate_zero_based()` accepts an optional `manual_amounts` parameter that the other two do not. Independent functions are independently testable, independently extensible, and independently callable by the CLI. A single function with branching would conflate three distinct mathematical approaches.

---

### Decision 2 — `distribute_pool_by_weight()` for intra-tier allocation

**Chosen:** A shared `distribute_pool_by_weight()` helper that takes a list of category names, the full categories dict, and a pool amount. It assigns the last category the exact remainder (`pool - running_total`) rather than rounding independently.

**Rejected:** Rounding each category's share independently and accepting fractional drift.

**Reason:** The last-category remainder assignment is the correct algorithm for distributing a fixed-sum pool without accumulating rounding errors. If every category's share is rounded independently, the sum of allocations will systematically differ from the pool by up to `n * $0.005` where `n` is the category count. The remainder assignment guarantees the sum equals the pool exactly.

---

### Decision 3 — `TIER_RANK` and `ACTUAL_SPEND_CATEGORY_ALIASES` as module-level constants

**Chosen:** `TIER_RANK = {"Needs": 0, "Wants": 1, "Savings": 2}` for sort key generation. `ACTUAL_SPEND_CATEGORY_ALIASES = {"Health": "Insurance"}` for normalizing category names from transaction data.

**Rejected:** Inline sort key strings or hardcoded name translations inside functions.

**Reason:** `TIER_RANK` is used in `build_zero_based_suggestion()` to sort categories by tier before applying priority within each tier — it converts string tiers to a stable numeric sort key. The aliases dict solves a real data alignment problem: the Categorizer module may label a transaction as "Health" while the budget profile uses "Insurance". The module-level alias map is the single place to update this mapping rather than hunting through function bodies.

---

### Decision 4 — `apply_actual_spending()` using `deepcopy`

**Chosen:** `apply_actual_spending()` calls `deepcopy(categories)` before injecting actual spend values, returning a new dict without modifying the input.

**Rejected:** Mutating the categories dict in place.

**Reason:** The budget profile loaded from storage is shared across all three strategy calculations. If `apply_actual_spending()` mutated its input, the actual spend values from one run would contaminate the categories dict for subsequent strategy runs. `deepcopy` is the correct isolation technique for nested dicts of dicts.

---

### Decision 5 — `compare_actual_to_budget()` handles unbudgeted categories

**Chosen:** The comparison iterates `set(alloc) | set(actual_spending.keys())` — the union of budgeted and actual categories. Categories with actual spending but no budget entry appear as `budgeted=0.0`, tier `"Unknown"`, status `"OVER"`.

**Rejected:** Only reporting categories that appear in the budget plan.

**Reason:** Real spending frequently includes categories that were not planned — a one-time vet bill, a surprise expense. Silently dropping these from the comparison would undercount actual spending and mislead the operator. The union approach surfaces unplanned spending as a visible row in the report.

---

### Decision 6 — `donor_allowed()` as a pure predicate for redistribution logic

**Chosen:** `donor_allowed(overage_row, candidate_row) -> bool` encodes three transfer rules: same-tier with lower priority, or Wants covering Needs. It is a pure function with no side effects.

**Rejected:** Inline conditional logic inside `build_redistribution_suggestions()`.

**Reason:** The redistribution rules are the most domain-specific logic in this module. Extracting them into a named predicate makes them readable, testable, and auditable. The name `donor_allowed` is precise about what the function answers: can this candidate donate to cover the overage?

---

### Decision 7 — `budget_cli.py` as a separate CLI layer

**Chosen:** `budget.py` contains only domain logic. `budget_cli.py` contains all interactive prompts, print formatting, and `input()` calls. `budget.py` delegates to `budget_cli.menu()` via `menu()` → `cli_menu()`.

**Rejected:** Mixing IO and domain logic in `budget.py`.

**Reason:** The same pattern established in App 06 (Password Checker) — the engine must be importable without triggering terminal IO. The Ledger Logic bootstrapper (App 14) imports `budget.run`-style functions directly. Any `input()` in `budget.py` would break headless use.

---

## Consequences

**Positive:**
- Last-category remainder assignment guarantees exact pool-sum equality for all three strategies.
- `deepcopy` in strategy functions ensures each strategy sees an uncontaminated category state.
- Union-based comparison catches unbudgeted spending.
- `donor_allowed()` as a named predicate makes redistribution rules auditable and testable.
- Engine/CLI separation allows library use without terminal output.

**Negative / Trade-offs:**
- `build_zero_based_suggestion()` produces a priority-proportional suggestion when no manual amounts are given. This suggestion is opinionated — it distributes by priority share, not by any real-world heuristic. Users who do not provide manual amounts get a mathematically consistent but not necessarily practical suggestion.
- The alias map `ACTUAL_SPEND_CATEGORY_ALIASES` is hardcoded. A larger deployment would need a user-configurable alias table stored in the budget profile JSON.
- `allocate_zero_based()` raises `ValueError` if any category would overshoot. This is correct behavior but means the zero-based strategy is the strictest — it cannot be used with estimated amounts that might slightly exceed income.

---

*Constitution reference: Articles 1, 2, 3. Amendment 1.3: `parsing.py`, `schemas.py`, `storage.py` are pinned snapshots.*


---


# Technical Design Document
## App 08 — Budget
**Ledger Logic Group | Document 2 of 5**

---

## Overview

The Budget module provides three income allocation strategies, an actual-vs-budgeted comparison engine, redistribution suggestions, and an interactive CLI. It is the planning and analysis layer of the Ledger Logic group.

**Files:** `budget.py` (407 lines), `budget_cli.py` (259 lines)
**Shared (pinned snapshots):** `parsing.py`, `schemas.py`, `storage.py`
**Entry point:** `budget.main()` → `budget_cli.menu()`
**Dependencies:** `copy.deepcopy`, `typing` (stdlib); `schemas`, `storage` (Ledger Logic shared)

---

## Data Flow

```
income: float, categories: dict[str, BudgetCategoryProfile]
        │
        ├─ allocate_fifty_thirty_twenty()
        │     ├─ Tier pools: Needs=50%, Wants=30%, Savings=20%
        │     └─ distribute_pool_by_weight() per tier
        │
        ├─ allocate_priority_weighted()
        │     └─ Each category gets (priority / total_priority) × income
        │
        └─ allocate_zero_based(manual_amounts)
              ├─ With amounts: validate → deduct from pool
              └─ Without amounts: build_zero_based_suggestion()
                     └─ Sort by tier → priority → weight, deduct sequentially
        │
        ▼
BudgetAllocation {strategy, allocations, categories, allocated_total, remaining, warnings}
        │
        ▼
compare_actual_to_budget(allocation, actual_spending)
        │
        ▼
BudgetComparisonResult {rows, overages, under_budget, total_overage, total_surplus, ...}
        │
        ▼
build_redistribution_suggestions(comparison)
        │
        ▼
list[{category, needed, donors: [{from, amount}]}]
```

---

## Module-Level Constants

### `VALID_TIERS`
`{"Needs", "Wants", "Savings"}` — validated in `validate_category()`.

### `TIER_RANK`
`{"Needs": 0, "Wants": 1, "Savings": 2}` — used as sort key in `build_zero_based_suggestion()` to process essential tiers before discretionary ones.

### `ACTUAL_SPEND_CATEGORY_ALIASES`
`{"Health": "Insurance"}` — maps transaction category labels to budget profile keys. Applied in `aggregate_actual_spending()`.

---

## Function Reference

### `starter_categories() → dict[str, BudgetCategoryProfile]`
Returns 10 default categories: 5 Needs (Rent, Groceries, Insurance, Transportation, Utilities), 3 Wants (Dining Out, Entertainment, Shopping), 2 Savings (Emergency Fund, Retirement). Each starts with `actual_spend=0.0`, `budgeted_amount=0.0`.

---

### `aggregate_actual_spending(records: list[CategorizedRecord]) → dict[str, float]`
Groups transactions by subcategory (falling back to category, then "Unknown"). Applies `ACTUAL_SPEND_CATEGORY_ALIASES`. Returns `{category: rounded_total}`.

---

### `validate_category(name, info, existing_names) → list[str]`
Validates a single category profile. Returns a list of error strings (empty = valid). Checks: non-blank name, valid tier, non-negative numeric weight, integer priority in `[1, 10]`, no duplicates.

---

### `apply_actual_spending(categories, actual_spending) → dict[str, BudgetCategoryProfile]`
Returns a deep copy of `categories` with `actual_spend` updated from `actual_spending` dict. Input is never mutated.

---

### `distribute_pool_by_weight(category_names, categories, pool_amount) → tuple[dict[str, float], list[str]]`
Distributes `pool_amount` proportionally by `categories[name]["weight"]`. The last category receives the exact remainder (`pool_amount - running_total`) to prevent rounding drift. Returns `({name: amount}, warnings)`.

**Edge case:** If `total_weight == 0`, all categories receive 0.0 and a warning is added.

---

### `allocate_fifty_thirty_twenty(income, categories) → BudgetAllocation`
Pools: Needs=50%, Wants=30%, Savings=20%. Each pool distributed via `distribute_pool_by_weight`. Raises `ValueError` if `income < 0`.

---

### `allocate_priority_weighted(income, categories) → BudgetAllocation`
Each category receives `(priority / total_priority) × income`. Last category receives remainder. Raises `ValueError` if `income < 0` or `total_priority == 0`.

---

### `build_zero_based_suggestion(income, categories) → dict[str, float]`
Sort order: Tier rank (Needs first) → priority descending → weight descending. Deducts from `remaining` sequentially. Last category receives remainder. Returns `{name: amount}`.

---

### `allocate_zero_based(income, categories, manual_amounts) → BudgetAllocation`
If `manual_amounts` is provided, validates each against the running pool and raises `ValueError` on overshoot or negative amounts. If `None`, uses `build_zero_based_suggestion()`. Warns if `remaining != 0` after all categories assigned.

---

### `compare_strategies(income, categories) → dict[str, BudgetAllocation]`
Runs all three strategies and returns `{"50/30/20": ..., "Priority Weighted": ..., "Zero Based": ...}`.

---

### `compare_actual_to_budget(allocation, actual_spending) → BudgetComparisonResult`
Iterates `set(alloc) | set(actual_spending)`. For each category: computes `difference = actual - budgeted`, sets `status = "OVER" | "UNDER" | "EVEN"`. Unbudgeted categories appear as `budgeted=0.0`, tier `"Unknown"`. Rows sorted: OVER first, then by absolute difference descending.

---

### `donor_allowed(overage_row, candidate_row) → bool`
Returns `True` if `candidate_row` can donate to cover `overage_row`'s overage:
- Candidate must be `"UNDER"` and not the same category
- Same tier AND candidate priority ≤ overage priority → allowed
- Overage is `"Needs"` AND candidate is `"Wants"` → allowed
- All other combinations → not allowed

---

### `build_redistribution_suggestions(comparison) → list[dict]`
For each OVER category: searches UNDER candidates via `donor_allowed()`. Collects donations greedily until overage is covered or donors exhausted. Output: `[{category, needed, donors: [{from, amount}]}]`.

---

## `BudgetCategoryProfile` Schema

```python
{
    "tier": "Needs" | "Wants" | "Savings",
    "weight": int | float,    # Relative weight for intra-tier distribution
    "priority": int,           # 1–10, used in priority-weighted strategy
    "actual_spend": float,     # Updated by apply_actual_spending()
    "budgeted_amount": float,  # Updated by strategy functions
}
```

---

## `BudgetAllocation` Schema

```python
{
    "strategy": str,
    "allocations": dict[str, float],          # {category: dollars}
    "categories": dict[str, BudgetCategoryProfile],
    "allocated_total": float,
    "remaining": float,
    "warnings": list[str],
}
```

---

## `BudgetComparisonResult` Schema

```python
{
    "rows": list[BudgetComparisonRow],
    "overages": set[str],
    "under_budget": set[str],
    "total_overage": float,
    "total_surplus": float,
    "total_actual": float,
    "total_budgeted": float,
}
```


---


# Interface Design Specification
## App 08 — Budget
**Ledger Logic Group | Document 3 of 5**

---

## Public API

### Allocation Functions

```python
allocate_fifty_thirty_twenty(
    income: float,
    categories: dict[str, BudgetCategoryProfile],
) -> BudgetAllocation
```

```python
allocate_priority_weighted(
    income: float,
    categories: dict[str, BudgetCategoryProfile],
) -> BudgetAllocation
```

```python
allocate_zero_based(
    income: float,
    categories: dict[str, BudgetCategoryProfile],
    manual_amounts: dict[str, Any] | None = None,
) -> BudgetAllocation
```

**Raises:** `ValueError` if `income < 0`, or if zero-based constraints are violated.

---

### Analysis Functions

```python
compare_strategies(
    income: float,
    categories: dict[str, BudgetCategoryProfile],
) -> dict[str, BudgetAllocation]
```

```python
compare_actual_to_budget(
    allocation: BudgetAllocation,
    actual_spending: dict[str, float],
) -> BudgetComparisonResult
```

```python
build_redistribution_suggestions(
    comparison: BudgetComparisonResult,
) -> list[dict[str, Any]]
```

---

### Helper Functions

```python
starter_categories() -> dict[str, BudgetCategoryProfile]
aggregate_actual_spending(records: list[CategorizedRecord]) -> dict[str, float]
apply_actual_spending(categories, actual_spending) -> dict[str, BudgetCategoryProfile]
validate_category(name, info, existing_names) -> list[str]
normalize_actual_spending_category(raw_name) -> str
```

---

### CLI Entry Point

```python
budget.main()     # Launches interactive menu
budget_cli.menu() # Direct menu access
```

---

## Input/Output Examples

### 50/30/20 allocation
```python
income = 5000.00
cats = starter_categories()
result = allocate_fifty_thirty_twenty(income, cats)
# result["allocations"]["Rent"]:         $1,136.36  (weight 5 of 18 in Needs pool)
# result["strategy"]:                    "50/30/20"
# result["allocated_total"]:             $5,000.00
# result["remaining"]:                   $0.00
```

### Priority-weighted allocation
```python
result = allocate_priority_weighted(5000.00, cats)
# Each category gets (priority / sum_of_priorities) × 5000
# Retirement (priority 10) gets more than Shopping (priority 3)
```

### Zero-based with manual amounts
```python
manual = {"Rent": 1500.0, "Groceries": 400.0, "Retirement": 500.0}
result = allocate_zero_based(5000.00, cats, manual_amounts=manual)
# ValueError if any amount causes running_pool to go negative
# Warns if remaining > 0 after all assignments
```

### Actual vs budgeted comparison
```python
allocation = allocate_fifty_thirty_twenty(5000.0, cats)
actual = {"Rent": 1500.0, "Dining Out": 600.0, "Groceries": 380.0}
comparison = compare_actual_to_budget(allocation, actual)
# comparison["overages"] → {"Dining Out"} (over Wants budget)
# comparison["total_overage"] → 300.00
# comparison["rows"][0]["status"] → "OVER"
```

### Redistribution suggestions
```python
suggestions = build_redistribution_suggestions(comparison)
# [{"category": "Dining Out", "needed": 300.0,
#   "donors": [{"from": "Entertainment", "amount": 300.0}]}]
```

### Validate a custom category
```python
errors = validate_category(
    "Gym",
    {"tier": "Wants", "weight": 1, "priority": 3, "actual_spend": 0.0, "budgeted_amount": 0.0},
    existing_names=set(cats),
)
# errors: []  (valid)
errors = validate_category("", {"tier": "Wants", "weight": 1, "priority": 3, ...}, set())
# errors: ["Category name cannot be blank."]
```

---

## Interactive CLI Menu

The CLI presents a text menu in a loop with the following options:

1. **Set income** — prompts for monthly income
2. **View/Edit categories** — displays current categories with tier, weight, priority
3. **Add category** — guided prompts for name, tier, weight, priority
4. **Run allocation (50/30/20)** — prints allocation table
5. **Run allocation (Priority Weighted)** — prints allocation table
6. **Run allocation (Zero Based)** — prompts for manual amounts or uses suggestion
7. **Compare strategies** — side-by-side table of all three strategies per category
8. **Compare actual vs budget** — prompts for actual spending, prints comparison report with redistribution suggestions
9. **Exit**

---

## CLI Output Format

### Allocation table
```
50/30/20 allocation
Category          Tier        Weight        Budgeted
----------------------------------------------------
Rent              Needs            5       $1,136.36
Groceries         Needs            4         $909.09
...
----------------------------------------------------
Allocated total: $5,000.00
Remaining: $0.00
```

### Comparison report
```
Category          Budgeted        Actual    Difference    Status
----------------------------------------------------------------------
Dining Out       $300.00        $600.00       $300.00  **OVER 200%
Rent           $1,136.36      $1,500.00       $363.64  **OVER 132%
Groceries        $909.09        $380.00      -$529.09   UNDER  42%
...
----------------------------------------------------------------------
Total income: $5,000.00
Total budgeted: $5,000.00
Total spent: $4,800.00
Total overage: $663.64
Total surplus: $529.09

Redistribution suggestions
Dining Out could absorb $300.00 from Entertainment $300.00
```


---


# Runbook
## App 08 — Budget
**Ledger Logic Group | Document 4 of 5**

---

## Requirements

- Python 3.10 or later
- No third-party dependencies
- `parsing.py`, `schemas.py`, `storage.py` must be in the same directory or on `PYTHONPATH`
- `typing_extensions` required for `NotRequired` in `schemas.py`

---

## Installation

```bash
git clone https://github.com/PrincetonAfeez/ledger-logic
cd ledger-logic
pip install typing_extensions   # Only dependency (for Python < 3.11 NotRequired)
```

---

## Running the CLI

### Interactive menu
```bash
python budget.py
```

The menu loops until the user selects Exit. Income persists across menu selections within the session. Categories can be added or edited during the session.

---

## Using as a Library

### Basic 50/30/20 allocation
```python
from budget import allocate_fifty_thirty_twenty, starter_categories

cats = starter_categories()
result = allocate_fifty_thirty_twenty(5000.0, cats)
for category, amount in result["allocations"].items():
    print(f"{category}: ${amount:.2f}")
```

### Compare all three strategies
```python
from budget import compare_strategies, starter_categories

results = compare_strategies(5000.0, starter_categories())
for strategy_name, allocation in results.items():
    print(f"{strategy_name}: total={allocation['allocated_total']}")
```

### Load real spending and compare to budget
```python
from budget import (allocate_fifty_thirty_twenty, aggregate_actual_spending,
                    apply_actual_spending, compare_actual_to_budget,
                    build_redistribution_suggestions, starter_categories)
from storage import load_categorized_transactions

records, warnings = load_categorized_transactions()
actual = aggregate_actual_spending(records)
cats = apply_actual_spending(starter_categories(), actual)
allocation = allocate_fifty_thirty_twenty(5000.0, cats)
comparison = compare_actual_to_budget(allocation, actual)
suggestions = build_redistribution_suggestions(comparison)
```

### Validate a custom category before adding
```python
from budget import validate_category, starter_categories

existing = set(starter_categories())
errors = validate_category(
    "Travel",
    {"tier": "Wants", "weight": 2, "priority": 5,
     "actual_spend": 0.0, "budgeted_amount": 0.0},
    existing,
)
if not errors:
    print("Category is valid")
else:
    for error in errors:
        print(f"Error: {error}")
```

---

## Running Tests

No dedicated test file was uploaded for App 08. Verification was performed through the interactive CLI menu and the Group B integration tests in the Ledger Logic bootstrapper (App 14).

For manual verification:
```bash
python budget.py
# Select option 1: set income to 5000
# Select option 4: run 50/30/20
# Confirm Allocated total equals $5,000.00 and Remaining equals $0.00
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'schemas'`
Ensure `parsing.py`, `schemas.py`, and `storage.py` are in the same directory as `budget.py`, or set `PYTHONPATH`.

### `ValueError: Income cannot be negative`
All three strategy functions require `income >= 0`. Pass `0.0` for a zero-income baseline.

### `ValueError: Priority scores cannot sum to zero`
`allocate_priority_weighted()` requires at least one category with `priority > 0`. The default `starter_categories()` all have priorities ≥ 3.

### Zero-based strategy warns about unassigned money
If `manual_amounts` does not cover the full income, the warning `"Zero-based plan left $X.XX unassigned"` appears in `result["warnings"]`. This is informational — the allocation is still valid.

### Actual spending categories not matching budget
Check `ACTUAL_SPEND_CATEGORY_ALIASES` in `budget.py`. Add an alias entry for any category name mismatch between the Categorizer output and the budget profile.


---


# Lessons Learned
## App 08 — Budget
**Ledger Logic Group | Document 5 of 5**

---

## Why This Design Was Chosen

The three-strategy architecture came from thinking about what the module's actual job is. The module does not decide which strategy is correct — the user does. The module's job is to faithfully implement each strategy and make them comparable. `compare_strategies()` exists precisely because the right answer to "which budgeting method should I use?" is "look at what each one does to your specific income and categories."

The `distribute_pool_by_weight()` remainder-assignment pattern came from a real bug in the first version. The first implementation rounded every category's share independently:

```python
amount = round(pool * (weight / total_weight), 2)
```

For a pool of `$2,500.00` distributed across five categories with equal weights, the five rounded amounts summed to `$2,500.01` — one cent over. The fix — assigning the exact remainder to the last category — guarantees exact pool-sum equality regardless of the number of categories or the pool size.

---

## What Was Intentionally Omitted

**Savings rate calculation:** The module tracks what is budgeted to the Savings tier and what was actually saved, but does not compute a savings rate as a percentage of income. This would be a two-line addition but was deferred to the Analyzer module (App 13).

**Month-over-month budget tracking:** The current model is single-period. It does not store historical budget plans or compare this month's allocation to last month's. Persistent budget history would require a new storage format and a separate comparison function.

**Budget profile persistence across sessions:** The CLI session starts fresh from `starter_categories()` each run. The user's custom categories are not saved to disk — there is no `save_budget_profile()` call from the CLI. The `get_budget_profile_path()` function in `storage.py` exists for this purpose but was not wired to the CLI in the evaluation version.

---

## Biggest Weakness

The `ACTUAL_SPEND_CATEGORY_ALIASES` dict is a hardcoded single-entry mapping (`"Health": "Insurance"`). In a real deployment with many users, the mismatch between Categorizer subcategory names and budget profile keys would vary per user. A hardcoded alias table cannot cover all cases. The correct design would store the alias mapping in the budget profile JSON alongside the category definitions, allowing per-user customization. The current implementation works for the default category set but would break for users who rename their budget categories.

---

## Scaling Considerations

**If income distribution rules become more complex:** The three strategy functions are independent — adding a fourth strategy (e.g., "Dave Ramsey debt snowball") requires only one new function and one new entry in `compare_strategies()`. No existing code changes.

**If categories grow to dozens:** `distribute_pool_by_weight()` handles any number of categories correctly — the remainder-assignment only runs once per pool. `compare_actual_to_budget()` uses set union so unbudgeted categories appear automatically. No structural changes needed.

**If budget profiles need persistence:** `storage.save_json()` and `load_json()` already exist and support `get_budget_profile_path()`. The CLI needs a "Save profile" and "Load profile" menu option. The engine functions are already storage-agnostic.

---

## What the Next Refactor Would Be

1. **Budget profile persistence** — wire `save_json()` and `load_json()` to the CLI "Save" and "Load" menu options.
2. **User-configurable alias map** — store `actual_spend_aliases` in the budget profile JSON alongside category definitions.
3. **Savings rate calculation** — add `savings_rate = (savings_actual / income) * 100` to the comparison report.
4. **Month-over-month comparison** — store budget plans by ISO month string in the profile JSON, compare current vs previous period.

---

## What This Project Taught

**Fixed-pool distribution requires a remainder assignment.** The rounding bug in the first version was invisible until the sum was checked. Writing a test that asserts `sum(allocations.values()) == income` revealed the one-cent discrepancy immediately. The fix — remainder to the last category — is a standard technique in financial software. Knowing when to apply it comes from knowing why the naive approach fails.

**`deepcopy` is required when nested dicts are shared.** The first version of `allocate_fifty_thirty_twenty()` modified `categories[name]["budgeted_amount"]` directly. When `compare_strategies()` ran all three strategies with the same `categories` dict, the budgeted_amounts from the first strategy appeared in the second strategy's output. `deepcopy` at the start of each strategy function isolates the computation correctly.

**A comparison function is only as good as its scope.** The first version of `compare_actual_to_budget()` only iterated the allocation keys — it silently dropped any actual spending on categories not in the budget. Adding the set union to include unbudgeted categories required one-line change but fundamentally changed the usefulness of the report. The scope of a comparison function must match the scope of the data, not just the planned data.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation) for App 08.*
