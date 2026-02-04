# M03 Grid Search Results

**Generated:** 2026-01-31 19:31
**Configurations Tested:** 12

## Rankings by Fitness Score

| Rank | Config | Fitness | AUC_Bear | AUC_Bull | Cohen_D | GFC_Lag | COVID_Lag |
|------|--------|---------|----------|----------|---------|---------|-----------|
| 1 | paranoid_tight | 0.7557 | 0.830 | 0.656 | 1.80 | 10 | 5 |
| 2 | aggressive_tight | 0.7084 | 0.754 | 0.640 | 1.40 | 6 | 5 |
| 3 | fast_liq_standard | 0.6975 | 0.747 | 0.624 | 1.28 | 9 | 5 |
| 4 | fast_liq_tight | 0.6973 | 0.747 | 0.623 | 1.30 | 9 | 5 |
| 5 | aggressive_standard | 0.6578 | 0.752 | 0.641 | 1.36 | 19 | 5 |
| 6 | fed_focus_tight | 0.6562 | 0.678 | 0.624 | 0.74 | 5 | 5 |
| 7 | fed_focus_standard | 0.6561 | 0.677 | 0.625 | 0.73 | 5 | 5 |
| 8 | trend_heavy_tight | 0.6333 | 0.891 | 0.683 | 2.46 | 43 | 6 |
| 9 | trend_heavy_standard | 0.5827 | 0.891 | 0.683 | 2.41 | 52 | 7 |
| 10 | baseline_tight | 0.5551 | 0.841 | 0.663 | 1.94 | 52 | 5 |
| 11 | baseline_standard | 0.5479 | 0.838 | 0.663 | 1.91 | 52 | 6 |
| 12 | paranoid_standard | 0.5374 | 0.826 | 0.654 | 1.77 | 52 | 6 |

## Best Configuration

**Winner:** `paranoid_tight`

- **Fitness:** 0.7557
- **AUC Bear:** 0.830 (target >= 0.90)
- **AUC Bull:** 0.656 (target >= 0.90)
- **Cohen's D:** 1.80 (target >= 2.0)
- **GFC Lag:** 10 days
- **COVID Lag:** 5 days

> [!WARNING]
> Phase 1 FAILED. Consider exploring additional archetypes.

## Archetype Comparison (Best per Archetype)

| Archetype | Best VIX | Fitness | AUC_Bear | Cohen_D |
|-----------|----------|---------|----------|---------|
| baseline | tight | 0.5551 | 0.841 | 1.94 |
| paranoid | tight | 0.7557 | 0.830 | 1.80 |
| fed_focus | tight | 0.6562 | 0.678 | 0.74 |
| aggressive | tight | 0.7084 | 0.754 | 1.40 |
| trend_heavy | tight | 0.6333 | 0.891 | 2.46 |
| fast_liq | standard | 0.6975 | 0.747 | 1.28 |
