# How to Insert Cells into sprint_summary_eda.ipynb

Three groups. Copy code from `sprint_eda_new_cells.md`, paste into notebook. Done.

---

## §1b — After cell `81f9f264` (churn B tenure), Before §2

### Markdown Cell
```markdown
### §1b — REVERSE-ENGINEERING REGIME FROM BREAKOUT COUNTS (NEW)
Can breakout supply predict regime? Chart daily/weekly breakout counts vs SPY/QQQ returns/MA.
```

### Code Cell
Copy `breakout_daily_counts` from `sprint_eda_new_cells.md`

### Code Cell
Copy `breakout_regime_viz` from `sprint_eda_new_cells.md`

---

## Q3 — After cell `c14950b3` (regime price charts), Before §3

### Markdown Cell
```markdown
### Q3 — Score Gate Efficacy: Deployed vs Rejected (ACTIONABLE)
Does the 0.6 gate filter bad trades or just noise? Compare equity fans.
```

### Code Cell
Copy `q3_rejected_fan_prep` from `sprint_eda_new_cells.md`

### Code Cell
Copy `q3_rejected_fan_compare` from `sprint_eda_new_cells.md`

### Code Cell
Copy `q3_rejected_fan_assertions` from `sprint_eda_new_cells.md`

---

## Q5 — After Q3 cells above, Before §3

### Markdown Cell
```markdown
### Q5 — Macro Regression: Predict Failure Days (RESEARCH)
Can SPY regime, momentum, and VIX predict forward returns < 0 on trade date?
```

### Code Cell
Copy `q5_macro_regression_prep` from `sprint_eda_new_cells.md`

### Code Cell
Copy `q5_macro_regression_model` from `sprint_eda_new_cells.md`

### Code Cell
Copy `q5_macro_regression_robustness` from `sprint_eda_new_cells.md`

### Code Cell (optional)
Copy `q5_macro_regression_deploy_test` from `sprint_eda_new_cells.md`

---

## Then Run

Execute all cells. Watch for:
- Print output (self-checks should pass ✓)
- Charts saved to `data/model_output_eda/sprint_summary/`
- Q3 output: deployed mean > rejected?
- Q5 output: AUC score?
