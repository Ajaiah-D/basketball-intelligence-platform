"""Dev Lab - password-gated SQL workbench over the warehouse.

Gated by DEV_PASSWORD in .env (never committed). The connection is
read-only, so DDL/DML statements fail at the database level.
"""

import io
import time

import duckdb
import pandas as pd
import streamlit as st

from dashboard.lib import config, db
from dashboard.lib import viz

EXAMPLE_QUERY = """\
-- Example: top 10 scorers (min 40 games)
select player_name, count(*) as gp, round(avg(points), 1) as ppg
from main_staging.stg_player_game_logs
group by 1
having count(*) >= 40
order by ppg desc
limit 10
"""


def _gate() -> bool:
    expected = config.dev_password()
    if not expected:
        st.error("Dev Lab is locked: set `DEV_PASSWORD` in `.env` (local) or the "
                 "app's secrets (cloud), then restart.")
        return False
    if st.session_state.get("dev_ok"):
        return True
    with st.form("dev_gate"):
        pw = st.text_input("Dev password", type="password")
        if st.form_submit_button("Unlock") and pw == expected:
            st.session_state["dev_ok"] = True
            st.rerun()
        elif pw:
            st.warning("Wrong password.")
    return False


def _schema_browser() -> None:
    with st.expander("Schema browser", expanded=False):
        cols = db.q(
            """
            select table_schema || '.' || table_name as "table",
                   string_agg(column_name || ' ' || lower(data_type), ', '
                              order by ordinal_position) as columns
            from information_schema.columns
            where table_schema in ('raw', 'main_staging')
            group by 1 order by 1
            """
        )
        for r in cols.itertuples():
            st.markdown(f"**`{r.table}`**")
            st.caption(r.columns)


def _run_query(sql: str) -> None:
    t0 = time.perf_counter()
    try:
        with duckdb.connect(str(db.DB_PATH), read_only=True) as con:
            result = con.execute(sql).df()
    except Exception as exc:
        st.error(f"Query failed: {exc}")
        return
    st.session_state["dev_result"] = result
    st.session_state["dev_elapsed"] = time.perf_counter() - t0


def _exports(df: pd.DataFrame) -> None:
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    c1.download_button("Export CSV", df.to_csv(index=False).encode(),
                       "query_result.csv", "text/csv", width="stretch")
    c2.download_button("Export JSON", df.to_json(orient="records", date_format="iso").encode(),
                       "query_result.json", "application/json", width="stretch")
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    c3.download_button("Export Parquet", buf.getvalue(), "query_result.parquet",
                       width="stretch")


def _chart_builder(df: pd.DataFrame) -> None:
    st.markdown("**Quick chart**")
    numeric = df.select_dtypes("number").columns.tolist()
    if not numeric:
        st.caption("No numeric columns in the result to chart.")
        return
    c1, c2, c3, c4 = st.columns(4)
    kind = c1.selectbox("Type", ["bar", "line", "scatter", "area"])
    x = c2.selectbox("X axis", df.columns)
    y = c3.selectbox("Y axis", numeric)
    color_options = ["(none)"] + [c for c in df.columns if c not in (x, y)]
    color = c4.selectbox("Series (color)", color_options)
    try:
        fig = viz.quick_chart(df, kind, x, y, None if color == "(none)" else color)
        st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
    except ValueError as exc:
        st.warning(str(exc))


def render() -> None:
    st.markdown("## Dev Lab")
    if not _gate():
        return

    st.caption("Read-only SQL over the warehouse. Schemas: `raw` (API mirrors) "
               "and `main_staging` (cleaned dbt views).")
    _schema_browser()

    sql = st.text_area("SQL", value=st.session_state.get("dev_sql", EXAMPLE_QUERY),
                       height=180, label_visibility="collapsed")
    if st.button("Run query", type="primary"):
        st.session_state["dev_sql"] = sql
        _run_query(sql)

    result = st.session_state.get("dev_result")
    if result is None:
        return
    st.caption(f"{len(result):,} rows x {len(result.columns)} cols - "
               f"{st.session_state.get('dev_elapsed', 0) * 1000:.0f} ms")
    st.dataframe(result, hide_index=True, height=min(420, 40 + 35 * len(result)))
    _exports(result)
    st.divider()
    _chart_builder(result)
