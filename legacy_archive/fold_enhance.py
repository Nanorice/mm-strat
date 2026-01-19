def get_enhanced_folds(start_year=2003, current_date="2025-12-02"):
    """
    Generates a dense, granular fold set to maximize validation confidence.
    """
    folds = []
    
    # --- STRATEGY A: The "Deep History" Validation (Annual Steps) ---
    # Goal: Prove the model survives 2012, 2015, 2018, 2022 (Bear/Chop years).
    # We start testing in 2012 (giving us 9 years of training data 2003-2011).
    for test_year in range(2012, 2025):
        train_start = "2003-01-01"
        train_end = f"{test_year - 1}-12-31"
        
        test_start = f"{test_year}-01-01"
        test_end = f"{test_year}-12-31"
        outcome_limit = f"{test_year + 1}-03-31" # 90-day natural exit buffer
        
        folds.append({
            'fold_name': f"History_Test_{test_year}",
            'train': (train_start, train_end),
            'test': (test_start, test_end),
            'outcome_limit': outcome_limit
        })

    # --- STRATEGY B: The "Current Regime" Tune (Quarterly Steps) ---
    # Goal: Zoom in on 2024-2025 to see if the model is adapting to the AI Boom.
    # We perform quarterly splits for the last 18 months.
    
    # Q1 2024
    folds.append({
        'fold_name': "Recent_2024_Q1",
        'train': ("2016-01-01", "2023-12-31"), # NOTE: Using Modern Era (2016+) Start
        'test': ("2024-01-01", "2024-03-31"),
        'outcome_limit': "2024-06-30"
    })
    
    # Q2 2024
    folds.append({
        'fold_name': "Recent_2024_Q2",
        'train': ("2016-01-01", "2024-03-31"),
        'test': ("2024-04-01", "2024-06-30"),
        'outcome_limit': "2024-09-30"
    })
    
    # Q3 2024
    folds.append({
        'fold_name': "Recent_2024_Q3",
        'train': ("2016-01-01", "2024-06-30"),
        'test': ("2024-07-01", "2024-09-30"),
        'outcome_limit': "2024-12-31"
    })

    # --- STRATEGY C: The "Live Fire" Test (2025 YTD) ---
    # This is your most important fold.
    folds.append({
        'fold_name': "LIVE_Regime_2025",
        'train': ("2003-01-01", "2024-12-31"), # Train on EVERYTHING
        'test': ("2025-01-01", current_date),
        'outcome_limit': current_date # Hard stop at today
    })

    return folds