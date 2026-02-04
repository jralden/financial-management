# Financial Management Vision

## Overview

A suite of tools and dashboard components to manage personal finances across multiple accounts and institutions, with a focus on bond portfolio optimization and automated data acquisition.

**Primary Institutions:**
- Fidelity (3 accounts: Brokerage, 401K-1, 401K-2) - Primary investment accounts, bonds and stocks
- Chase (Checking) - Cash account
- UK Online Bank - Cash account
- Credit Cards - Spending tracking (future)

---

## Vision Statements

### VS-1: Quick Account Status Dashboard

**Problem:** I need to quickly check the status of my primary accounts frequently throughout the day.

**Desired Solution:** A dashboard view (likely in System-Dashboard) showing:
- Current balances for the three Fidelity accounts
- Current balances for Chase checking and UK bank account
- Daily change indicators (increase/decrease)
- Possibly other elements to be determined during detailed design

**Value:** Eliminates need to log into multiple sites throughout the day; provides at-a-glance financial awareness.

---

### VS-2: Bond Income Projection by Tax Year

**Problem:** Fidelity's Positions page shows bond holdings but doesn't provide a yearly bond revenue projection. I need to see projected income from bonds summarized by tax year for planning purposes.

**Desired Solution:** A view (dashboard component or report) that:
- Reads bond holdings from all three Fidelity accounts
- Calculates projected coupon payments by calendar/tax year
- Summarizes income across accounts
- Accounts for bonds maturing mid-year

**Value:** Enables tax planning and income forecasting that Fidelity doesn't provide natively.

---

### VS-3: Maturing Bonds Tracking

**Problem:** My bond investments are short-term (typically < 5 years to maturity). Holding to maturity eliminates market pricing risk, but bonds need to be replaced as they mature.

**Desired Solution:** A list of maturing bonds showing:
- Bonds approaching maturity (sorted by maturity date)
- Face value and expected return at maturity
- Timeline view (what's maturing when)
- Could be dashboard component or separate report

**Value:** Proactive visibility into upcoming reinvestment needs.

---

### VS-4: Bond Evaluation and Portfolio Optimization Tool

**Problem:** I have existing Python code for bond portfolio construction that needs improvement. Current limitations:
- Only handles Corporate bonds (no US Treasury support)
- No systematic testing/debugging
- Cannot evaluate replacement of existing holdings with better options
- Fidelity-selected bonds in my portfolio may be suboptimal

**Desired Solution:** A reimplemented bond evaluation system that:
- Runs daily to identify available replacement bonds
- Evaluates bonds for maximum cash production over time (hold-to-maturity strategy)
- Compares potential replacements against current holdings with projected improvement
- Supports both Corporate bonds AND US Treasuries
- Has comprehensive test coverage
- Produces actionable recommendations

**Existing Code Reference:** `/Users/johnalden/Documents/Development/Financial/Bond_Management` contains the current Python implementation with:
- Bond ranking by income/profit/composite scores
- Ladder optimization with diversification constraints
- Fidelity CSV parsing
- Payment schedule calculations

**Value:** Systematic, data-driven bond selection replacing ad-hoc decisions; identifies portfolio improvement opportunities.

---

### VS-5: Fidelity Data Automation (Foundational)

**Problem:** Current bond evaluation relies on manual CSV export from Fidelity. Dashboard functionality would require automated data access. Fidelity uses 2FA, but my desktop machine is recognized and doesn't prompt for authentication.

**Desired Solution:** Explore and implement automated Fidelity data capture:
- Authenticate and maintain session programmatically
- Extract account balances for dashboard (VS-1)
- Extract bond positions for income projection (VS-2)
- Download bond search results CSV for evaluation (VS-4)
- Potentially use Puppeteer/Playwright for browser automation

**Risk:** 2FA bypass may not be feasible; need to validate approach early.

**Priority:** HIGH - This is a foundational capability that enables VS-1, VS-2, and partially VS-4. Should be explored first to validate feasibility.

**Value:** Eliminates manual data gathering; enables real-time dashboard updates and daily automated analysis.

---

## Dependencies and Sequencing

```
VS-5 (Fidelity Automation) ─────┬──────> VS-1 (Account Dashboard)
        │                       │
        │                       └──────> VS-2 (Bond Income Projection)
        │
        └─────────────────────────────> VS-4 (Bond Evaluation) [partial]
                                              │
VS-3 (Maturing Bonds) <───────────────────────┘
```

**Recommended Approach:**
1. **Phase 0:** Validate Fidelity automation feasibility (VS-5)
2. **Phase 1:** If automation works, build dashboard components (VS-1, VS-2, VS-3)
3. **Phase 2:** Reimplement bond evaluation tool (VS-4) with improvements
4. **Parallel:** VS-4 can proceed with manual CSV input while automation is developed

---

## Open Questions

1. Should the dashboard be a System-Dashboard panel (Swift/native) or a separate web-based tool?
2. How should data flow between Python analysis tools and Swift dashboard?
3. What's the update frequency needed for dashboard balances?
4. Should bond evaluation run as a scheduled job or on-demand?
5. What credit card tracking is needed (VS-1 mentions "other elements")?

---

## Technical Considerations

**Potential Architecture:**
- Python backend for data acquisition and financial calculations
- Reuse/refactor Bond_Management code for bond analysis
- System-Dashboard Swift panel for native macOS display
- Local data store (SQLite or JSON) for caching account data
- Scheduled jobs for daily bond evaluation

**Existing Assets:**
- Bond_Management: Bond models, ranking, optimization, CSV parsing
- Financial_Modeler: Income projection, payment schedules, matrix calculations
- System-Dashboard: Panel plugin architecture, service injection, VS Code patterns
