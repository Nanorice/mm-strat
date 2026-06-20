$ErrorActionPreference = "Stop"

Write-Host "1. Running Binary Calibrated (Full History)..."
python scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1_cal_full.html --apply-calibration --skip-sepa-match

Write-Host "2. Running Binary Uncalibrated (Full History)..."
python scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1_uncal_full.html --skip-sepa-match

Write-Host "3. Running 4-Class Calibrated (Full History)..."
python scripts/build_model_card.py --model m01_prototype_2003_2026/v2 --output model_cards/m01_prototype_v2_cal_full.html --apply-calibration --skip-sepa-match

Write-Host "4. Running 4-Class Uncalibrated (Full History)..."
python scripts/build_model_card.py --model m01_prototype_2003_2026/v2 --output model_cards/m01_prototype_v2_uncal_full.html --skip-sepa-match

Write-Host "5. Running Grid Comparison..."
python scripts/compare_models.py --cards model_cards/m01_prototype_v2_uncal_full.json model_cards/m01_prototype_v2_cal_full.json model_cards/m01_binary_v1_uncal_full.json model_cards/m01_binary_v1_cal_full.json --output C:\Users\Hang\.gemini\antigravity-ide\brain\dc78040f-054b-430a-a380-36a2327a04db\grid_comparison_full.md

Write-Host "Done!"
