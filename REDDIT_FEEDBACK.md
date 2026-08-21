# Reddit feedback post draft

**Title:** I built a local DAX-to-SQL compiler and semantic-model workbench — looking for blunt feedback

I’m testing the smallest useful open-core version of a project that translates supported DAX expressions into DuckDB SQL.

The build includes the compiler, semantic-model browser, all current data connectors, all 31 existing Plotly visuals, basic filtering/formatting, and a tabular data preview. It runs locally and has no product telemetry.

I intentionally left out custom SVG/IBCS charts, Tableau visuals/import, static report objects, matrix/table report visuals, auto-generation, ML features, subscriptions, licensing, and server/multi-user features. I want to find out whether the core workflow is useful before expanding the public surface.

I would especially value feedback from people who work with DAX, Power BI semantic models, DuckDB, or BI migration:

1. Does the generated SQL match what you expect from the DAX expression?
2. Is the semantic-model and relationship view clear enough to debug a result?
3. Can you connect a realistic source without unnecessary setup?
4. Which single missing capability would stop you using it a second time?
5. Where does the UI make you hesitate or guess?

Repository: `<link>`

Please use synthetic or anonymized data and never include credentials in reports. There is a sample project and a structured feedback issue template in the repository.
