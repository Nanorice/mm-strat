"""
Fundamental Column Mapping

Centralized mapping between FMP API column names and standardized internal names.
This ensures consistency across the fundamental data pipeline.
"""

# ============================================================================
# CASH FLOW STATEMENT - FMP to Standard Name Mapping
# ============================================================================
CASH_FLOW_COLUMN_MAP = {
    # Operating Activities
    'netCashProvidedByOperatingActivities': 'operatingCashFlow',
    'deferredIncomeTax': 'deferredIncomeTax',
    'stockBasedCompensation': 'stockBasedCompensation',
    'changeInWorkingCapital': 'changeInWorkingCapital',
    'otherNonCashItems': 'otherNonCashItems',
    
    # Investing Activities
    'investmentsInPropertyPlantAndEquipment': 'capitalExpenditure',
    'acquisitionsNet': 'acquisitionsNet',
    'purchasesOfInvestments': 'purchasesOfInvestments',
    'salesMaturitiesOfInvestments': 'salesMaturitiesOfInvestments',
    'otherInvestingActivities': 'otherInvestingActivities',
    'netCashUsedForInvestingActivites': 'cashFlowFromInvesting',  # Note: FMP has typo "Activites"
    
    # Financing Activities
    'netDebtIssuance': 'netDebtIssuance',
    'longTermNetDebtIssuance': 'longTermNetDebtIssuance',
    'shortTermNetDebtIssuance': 'shortTermNetDebtIssuance',
    'netStockIssuance': 'netStockIssuance',
    'netCommonStockIssuance': 'netCommonStockIssuance',
    'commonStockIssuance': 'commonStockIssuance',
    'commonStockRepurchased': 'commonStockRepurchased',
    'netPreferredStockIssuance': 'netPreferredStockIssuance',
    'netDividendsPaid': 'netDividendsPaid',
    'commonDividendsPaid': 'commonDividendsPaid',
    'preferredDividendsPaid': 'preferredDividendsPaid',
    'otherFinancingActivities': 'otherFinancingActivities',
    'netCashUsedProvidedByFinancingActivities': 'cashFlowFromFinancing',
    
    # Cash Flow Summary
    'effectOfForexChangesOnCash': 'effectOfForexChangesOnCash',
    'netChangeInCash': 'netChangeInCash',
    'cashAtEndOfPeriod': 'cashAtEndOfPeriod',
    'cashAtBeginningOfPeriod': 'cashAtBeginningOfPeriod',
    'freeCashFlow': 'freeCashFlow',
    'operatingCashFlow': 'operatingCashFlow',
    'capitalExpenditure': 'capitalExpenditure',
    
    # Tax & Interest
    'incomeTaxesPaid': 'incomeTaxesPaid',
    'interestPaid': 'interestPaid',
}

# ============================================================================
# DERIVED METRICS - Columns we want to keep for ML features
# ============================================================================
DERIVED_FUNDAMENTAL_COLUMNS = [
    # Growth metrics (calculated by FundamentalProcessor)
    'revenue_growth_yoy',
    'eps_growth_yoy',
    'net_income_growth_yoy',
    'revenue_accel',
    'eps_accel',
    'inventory_growth_yoy',
    'inventory_vs_sales_spread',

    # Long-term trend metrics (calculated by FundamentalProcessor)
    'revenue_cagr_3y',
    'eps_stability_score',

    # Safety metrics (calculated by FundamentalProcessor)
    'debt_to_equity',
    'current_ratio',
    'quick_ratio',

    # Operating metrics (calculated by FundamentalProcessor)
    'gross_margin',
    'operating_margin',
    'net_margin',
    'roe',
    'roa',
    'gross_margin_trend',         # Margin expansion/contraction
    'earnings_quality_score',     # Operating cash flow quality
    'fcf_margin',                 # Free cash flow margin

    # Hybrid metrics (calculated by FundamentalMerger)
    'pe_ratio',
    'ps_ratio',
    'pb_ratio',
    'peg_adjusted',

    # CRITICAL: Raw columns needed for feature calculations
    # These would normally be in RAW_FUNDAMENTAL_COLUMNS, but we need them
    # for calculating quality metrics (earnings_quality_score, fcf_margin)
    'operatingCashFlow',          # Needed for: earnings_quality_score
    'freeCashFlow',               # Needed for: fcf_margin
    'netIncome',                  # Needed for: earnings_quality_score
    'revenue',                    # Needed for: fcf_margin

    # Metadata
    'days_since_report',
    'days_since_earnings',
    'is_stale',
    'has_fundamentals',
    'is_declining_earnings',
    'filing_date_matched',
    'fiscal_date',
    'fiscal_period',
]

# ============================================================================
# RAW FUNDAMENTAL COLUMNS - Original FMP columns (usually not needed for ML)
# ============================================================================
RAW_FUNDAMENTAL_COLUMNS = [
    # Metadata
    'symbol', 'reportedCurrency', 'cik', 'accepted_date', 'fiscalYear', 'statement_type',
    
    # Income Statement
    # NOTE: 'revenue' and 'netIncome' moved to DERIVED_FUNDAMENTAL_COLUMNS (needed for fcf_margin, earnings_quality_score)
    'costOfRevenue', 'grossProfit', 'operatingIncome',
    'eps', 'epsDiluted', 'ebitda', 'ebit',
    'researchAndDevelopmentExpenses', 'generalAndAdministrativeExpenses',
    'sellingAndMarketingExpenses', 'sellingGeneralAndAdministrativeExpenses',
    'otherExpenses', 'operatingExpenses', 'costAndExpenses',
    'netInterestIncome', 'interestIncome', 'interestExpense',
    'depreciationAndAmortization', 'nonOperatingIncomeExcludingInterest',
    'totalOtherIncomeExpensesNet', 'incomeBeforeTax', 'incomeTaxExpense',
    'netIncomeFromContinuingOperations', 'netIncomeFromDiscontinuedOperations',
    'otherAdjustmentsToNetIncome', 'netIncomeDeductions', 'bottomLineNetIncome',
    'weightedAverageShsOut', 'weightedAverageShsOutDil',
    
    # Balance Sheet
    'cashAndCashEquivalents', 'shortTermInvestments', 'cashAndShortTermInvestments',
    'netReceivables', 'accountsReceivables', 'otherReceivables', 'inventory',
    'prepaids', 'otherCurrentAssets', 'totalCurrentAssets',
    'propertyPlantEquipmentNet', 'goodwill', 'intangibleAssets',
    'goodwillAndIntangibleAssets', 'longTermInvestments', 'taxAssets',
    'otherNonCurrentAssets', 'totalNonCurrentAssets', 'otherAssets', 'totalAssets',
    'totalPayables', 'accountPayables', 'otherPayables', 'accruedExpenses',
    'shortTermDebt', 'capitalLeaseObligationsCurrent', 'taxPayables',
    'deferredRevenue', 'otherCurrentLiabilities', 'totalCurrentLiabilities',
    'longTermDebt', 'capitalLeaseObligationsNonCurrent', 'deferredRevenueNonCurrent',
    'deferredTaxLiabilitiesNonCurrent', 'otherNonCurrentLiabilities',
    'totalNonCurrentLiabilities', 'otherLiabilities', 'capitalLeaseObligations',
    'totalLiabilities', 'treasuryStock', 'preferredStock', 'commonStock',
    'retainedEarnings', 'additionalPaidInCapital',
    'accumulatedOtherComprehensiveIncomeLoss', 'otherTotalStockholdersEquity',
    'totalStockholdersEquity', 'totalEquity', 'minorityInterest',
    'totalLiabilitiesAndTotalEquity', 'totalInvestments', 'totalDebt', 'netDebt',
    
    # Cash Flow (standardized names after mapping)
    # NOTE: 'operatingCashFlow' and 'freeCashFlow' moved to DERIVED_FUNDAMENTAL_COLUMNS (needed for quality metrics)
    'capitalExpenditure',
    'deferredIncomeTax', 'stockBasedCompensation', 'changeInWorkingCapital',
    'otherNonCashItems', 'otherWorkingCapital', 'accountsPayables',
    'cashFlowFromInvesting', 'acquisitionsNet',
    'purchasesOfInvestments', 'salesMaturitiesOfInvestments',
    'otherInvestingActivities', 'netDebtIssuance', 'longTermNetDebtIssuance',
    'shortTermNetDebtIssuance', 'netStockIssuance', 'netCommonStockIssuance',
    'commonStockIssuance', 'commonStockRepurchased', 'netPreferredStockIssuance',
    'netDividendsPaid', 'commonDividendsPaid', 'preferredDividendsPaid',
    'otherFinancingActivities', 'cashFlowFromFinancing',
    'effectOfForexChangesOnCash', 'netChangeInCash', 'cashAtEndOfPeriod',
    'cashAtBeginningOfPeriod', 'incomeTaxesPaid', 'interestPaid',
    
    # Unmapped FMP columns (still using original names)
    'netCashProvidedByOperatingActivities',
    'netCashProvidedByFinancingActivities', 
    'netCashProvidedByInvestingActivities',
    'investmentsInPropertyPlantAndEquipment',
]


def standardize_cash_flow_columns(df):
    """
    Rename FMP cash flow columns to standardized names.
    
    Args:
        df: DataFrame with FMP column names
        
    Returns:
        DataFrame with standardized column names
    """
    # Only rename columns that exist in the dataframe
    columns_to_rename = {k: v for k, v in CASH_FLOW_COLUMN_MAP.items() if k in df.columns}
    
    if columns_to_rename:
        df = df.rename(columns=columns_to_rename)
    
    return df


def get_columns_to_merge(include_raw: bool = False):
    """
    Get list of fundamental columns to merge into feature dataset.
    
    Args:
        include_raw: If True, include raw fundamental columns. 
                     If False, only include derived metrics (default).
    
    Returns:
        List of column names to merge
    """
    columns = DERIVED_FUNDAMENTAL_COLUMNS.copy()
    
    if include_raw:
        columns.extend(RAW_FUNDAMENTAL_COLUMNS)
    
    return columns
