# Architecture Documentation

This folder contains the master implementation plan and all feature-specific implementation plans for Plexis V2.

---

## Master Plan

| File | Purpose |
|---|---|
| [`implementation_plan.md`](./implementation_plan.md) | **Master blueprint.** 20-phase backend roadmap, architectural enhancements, Plexis Constitution. Read this first. |

---

## Feature Plans

Feature-specific plans are created alongside development. They provide implementation detail that the master plan intentionally omits.

| File | Status | Phase |
|---|---|---|
| *(none yet — created as development proceeds)* | — | — |

---

## Policy

1. **`implementation_plan.md` is the source of truth** for overall direction, development order, and architectural decisions.
2. **Feature plans** are encouraged for any non-trivial component. They coexist with the master plan — they do not replace it.
3. Feature plans are **living documents**. Create, update, expand, archive, or replace them freely.
4. Any significant change to the overall architecture must be **proposed with rationale** before modifying `implementation_plan.md`.
5. Default workflow:
   ```
   Review implementation_plan.md
   → Understand current phase
   → Review feature plan (if one exists)
   → Create feature plan if needed
   → Implement
   → Update feature plan
   ```
