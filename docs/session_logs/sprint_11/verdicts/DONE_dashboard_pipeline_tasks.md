# Dashboard and Pipeline Changes (Sprint 11)

## Dashboard Updates

### Page 1: Today Page (Screener Watchlist)
- **Market Cap**: Add a new column to display the market cap.
- **Ticker Hyperlink**: Convert the ticker name into a hyperlink directing to Finviz for more information (e.g., `https://finviz.com/stock?t=[TICKER]`).

### Page 2: Feature Time Series / Dataset EDA
- **Remove Feature Time Series**: Remove the current feature time series visualizations, as third-party websites offer better usability.
- **Dataset EDA Placeholder**: Replace it with a placeholder for Dataset EDA, should be using the pretrain eda report that's currently in the model lab page.
  - **Metrics**: Show target distribution, class imbalance, etc.
  - **Interactive**: Include a dropdown to check different label sets. This indicates the data eda has unique id by feature set. is this sufficient? assumption is that this report is to be run weekly, or daily, once data quality is confirmed. (this reminds me, we had issues with bad tickers, currently we are processing it in model training, but in reality we should treat them in phase 1. let's confirm the source of this error and see how to fix, and to prevent in the future. do we have dod change on price as part of data audit for phase 1?)
  - **Data Source**: Investigate using `t3_sepa_features` (note: verify load performance) and leverage existing pretrain EDA infrastructure.
  - **Pretrain Report**: Move the pretrain report here from the Model Lab page.

### Page 3: Model Lab
- **Pretrain Report Tab**: Remove this tab (moving its contents to Page 2).
- **Plots Tab**: Review and verify how the current graphs are generated.
- **Report (MD) Tab**: 
  - Evaluate the overlap with the new Model Card.
  - Convert the markdown report into an HTML report format.
- **Model Card Tab**: Add a new tab dedicated to displaying the Model Card.

### Page 4: Backtest Studio
- **Strategy Indicator**: Explicitly state which backtesting strategy is currently being used for the displayed runs.

### Page 5: Pipeline Health
- **T1 Ingestion Failures**: Add a section detailing which tickers failed T1 ingestion, the specific failure reason, and the number of days they have been failing (to aid in pruning inactive tickers).
- **Fundamental Updates Audit**: 
  - Show the most recently updated ticker for fundamentals, including a snapshot of key metrics (e.g., revenue) to confirm functionality.
  - Add a chart showing the number of financial reports fetched, grouped by quarter (to ensure fetching volume remains consistent).
- **Table Registry**: Update the tables section to reflect the active list of tables, ensuring it acts as a single source of truth consistent with `docs/manual_for_me.md`.
- **schematics** let's also add the mermaid flow chart to this page showing dataflow. how do we make sure this is not hardcoded and always point to the right file? shall we move this chart out as a standalone file?
