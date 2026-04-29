import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
import json
from datetime import datetime

st.set_page_config(
    page_title="VAT Sales Trends",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Static column names ───────────────────────────────────────────────────────
ASIN_COL_SHEET   = "ASIN"
VAT_COL_SHEET    = "VAT Code"
ASIN_COL_AMAZON  = "(Child) ASIN"
SALES_COL_AMAZON = "Ordered Product Sales"
SHEET_HEADER_ROW = 2   # 0-indexed → row 3 in the spreadsheet

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_sheet_id(url: str):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def get_sheet_tabs(sheet_id: str):
    """
    Fetch all tab names using the gviz/tq JSON endpoint.
    Works with 'Anyone with the link' sharing — no login required.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json"
    try:
        r = requests.get(url, timeout=10)
        # gviz wraps response in  /*O_o*/  google.visualization.Query.setResponse({...});
        text = r.text
        # Strip the JS wrapper to get pure JSON
        text = re.sub(r"^[^(]+\(", "", text).rstrip(");")
        data = json.loads(text)
        sheets = data.get("table", {})
        # Sheet names live in the outer response under a non-standard key;
        # fall back to parsing the raw text for "sheetNames"
        raw_match = re.search(r'"sheetNames":\s*(\[[^\]]+\])', r.text)
        if raw_match:
            return json.loads(raw_match.group(1))
    except Exception:
        pass
    return []


def load_tab_as_df(sheet_id: str, tab_name: str):
    """
    Load a sheet tab via gviz CSV (works with 'Anyone with the link').
    Reads all rows with no header, then promotes row SHEET_HEADER_ROW (0-indexed) as columns.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab_name)}"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        # Read without treating any row as header
        df = pd.read_csv(io.StringIO(r.text), header=None, dtype=str)
        # Use SHEET_HEADER_ROW as column names
        df.columns = df.iloc[SHEET_HEADER_ROW].str.strip()
        # Data rows start after the header row
        df = df.iloc[SHEET_HEADER_ROW + 1:].reset_index(drop=True)
        # Drop fully empty rows/columns
        df = df.dropna(how="all", axis=1).dropna(how="all", axis=0)
        return df
    except Exception as e:
        st.error(f"Could not load tab '{tab_name}': {e}")
        return None


def norm_asin(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()


def map_vat_category(label: str) -> str:
    l = str(label).strip().lower()
    if any(x in l for x in ["standard", "20"]):
        return "20% Standard"
    if any(x in l for x in ["reduced", "5%", "5 %"]):
        return "5% Reduced"
    if any(x in l for x in ["zero", "0%", "0 %", "exempt", "free"]):
        return "0% Zero Rated"
    return "Unknown"


def parse_amazon_report(file):
    try:
        if file.name.lower().endswith(".csv"):
            df = pd.read_csv(file, encoding="utf-8-sig")
        else:
            df = pd.read_excel(file)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        st.error(f"Could not read '{file.name}': {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("Settings")
    st.divider()

    st.subheader("Google Sheet")
    st.caption("Share your sheet as **Anyone with the link → Viewer** before pasting the URL.")

    sheet_url  = st.text_input("Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/…")
    tab_name   = None
    sheet_id   = None
    sheet_tabs = []

    if sheet_url:
        sheet_id = extract_sheet_id(sheet_url)
        if not sheet_id:
            st.error("Could not find a Sheet ID in that URL.")
        else:
            with st.spinner("Fetching tabs…"):
                sheet_tabs = get_sheet_tabs(sheet_id)

            if sheet_tabs:
                tab_name = st.selectbox("Select tab", options=sheet_tabs)
            else:
                st.caption("Could not fetch tabs automatically. Type the tab name manually.")
                tab_name = st.text_input("Tab name", placeholder="e.g. Profit Calculator - VAT 20%")

    st.divider()
    st.caption("Amazon UK · VAT sales trend tracker")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
st.title("VAT Sales Trends")
st.caption("Match your Amazon UK business reports against your VAT catalogue and track 20% / 5% / 0% splits over time.")
st.divider()

# ── Step 1: Load Google Sheet ─────────────────────────────────────────────────
gsheet_df = None
vat_map   = {}

if sheet_id and tab_name:
    with st.spinner(f"Loading '{tab_name}'…"):
        gsheet_df = load_tab_as_df(sheet_id, tab_name)

    if gsheet_df is not None:
        missing = [c for c in [ASIN_COL_SHEET, VAT_COL_SHEET] if c not in gsheet_df.columns]
        if missing:
            available = "`, `".join(gsheet_df.columns.tolist())
            st.warning(
                f"Column(s) not found: **{', '.join(missing)}**  \n"
                f"Columns available: `{available}`"
            )
        else:
            vat_map = {
                norm_asin(pd.Series([r[ASIN_COL_SHEET]]))[0]: map_vat_category(r[VAT_COL_SHEET])
                for _, r in gsheet_df.iterrows()
                if pd.notna(r[ASIN_COL_SHEET]) and str(r[ASIN_COL_SHEET]).strip() not in ("", "nan")
            }
            st.success(f"Sheet loaded — **{len(vat_map):,}** ASINs mapped.")
            with st.expander("Preview mapping (first 20 rows)"):
                st.dataframe(gsheet_df[[ASIN_COL_SHEET, VAT_COL_SHEET]].head(20), use_container_width=True)
else:
    st.info("Paste your Google Sheet URL in the sidebar to get started.")

st.divider()

# ── Step 2: Upload Amazon reports ─────────────────────────────────────────────
st.subheader("Monthly Amazon Business Reports")
st.caption("One file per month (CSV or Excel). Download from Seller Central → Reports → Business Reports → Detail Page Sales and Traffic by Child ASIN.")

uploaded_files = st.file_uploader(
    "Upload files",
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

month_labels = {}
if uploaded_files:
    st.write("**Assign a month label to each file:**")
    cols = st.columns(min(len(uploaded_files), 4))
    for i, f in enumerate(uploaded_files):
        with cols[i % 4]:
            month_labels[f.name] = st.text_input(
                f.name,
                value=f.name.rsplit(".", 1)[0],
                key=f"lbl_{i}",
                placeholder="e.g. Jan 2025",
            )

st.divider()

# ── Step 3: Generate ─────────────────────────────────────────────────────────
ready = bool(uploaded_files and vat_map)
run   = st.button("Generate Trends", type="primary", disabled=not ready)

if not ready and uploaded_files and not vat_map:
    st.caption("Connect your Google Sheet in the sidebar to enable this button.")

if run and ready:
    results       = []
    unmatched_log = []
    progress      = st.progress(0, text="Processing…")

    for idx, f in enumerate(uploaded_files):
        month = month_labels.get(f.name, f.name)
        df    = parse_amazon_report(f)
        if df is None:
            continue

        missing_cols = [c for c in [ASIN_COL_AMAZON, SALES_COL_AMAZON] if c not in df.columns]
        if missing_cols:
            available_cols = "`, `".join(df.columns.tolist())
            st.warning(
                f"**{f.name}** — columns not found: `{'`, `'.join(missing_cols)}`  \n"
                f"Available: `{available_cols}`"
            )
            continue

        df = df[[ASIN_COL_AMAZON, SALES_COL_AMAZON]].copy()
        df.columns = ["ASIN", "Sales"]
        df["Sales"] = (
            df["Sales"].astype(str)
            .str.replace(r"[£,\s]", "", regex=True)
            .str.replace(r"[^\d\.-]", "", regex=True)
        )
        df["Sales"]        = pd.to_numeric(df["Sales"], errors="coerce").fillna(0)
        df["ASIN"]         = norm_asin(df["ASIN"])
        df["VAT Category"] = df["ASIN"].map(vat_map).fillna("Unmatched")

        unmatched_log.extend(
            [(month, a) for a in df[df["VAT Category"] == "Unmatched"]["ASIN"].unique()]
        )
        for cat, grp in df.groupby("VAT Category"):
            results.append({"Month": month, "VAT Category": cat, "Sales": grp["Sales"].sum()})

        progress.progress((idx + 1) / len(uploaded_files), text=f"Processed: {month}")

    progress.empty()

    if not results:
        st.error("No data could be processed. Check that column names match the expected format.")
        st.stop()

    # ── Build pivots ──────────────────────────────────────────────────────────
    df_res = pd.DataFrame(results)
    pivot  = df_res.pivot_table(
        index="Month", columns="VAT Category", values="Sales", aggfunc="sum"
    ).fillna(0)

    def try_parse(s):
        for fmt in ["%b %Y", "%B %Y", "%m/%Y", "%Y-%m", "%b_%Y", "%B_%Y", "%b%Y"]:
            try:
                return datetime.strptime(s.strip(), fmt)
            except Exception:
                pass
        return None

    parsed = [try_parse(m) for m in pivot.index]
    if all(p is not None for p in parsed):
        pivot = pivot.iloc[sorted(range(len(parsed)), key=lambda i: parsed[i])]

    chart_cats  = [c for c in pivot.columns if c != "Unmatched"]
    pivot_chart = pivot[chart_cats]
    pivot_pct   = pivot_chart.div(pivot_chart.sum(axis=1), axis=0) * 100

    # ── Metric cards ──────────────────────────────────────────────────────────
    latest  = pivot_pct.index[-1]
    row_pct = pivot_pct.loc[latest]

    st.subheader(f"Latest month — {latest}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Standard VAT (20%)", f"{row_pct.get('20% Standard', 0):.1f}%")
    c2.metric("Reduced VAT (5%)",   f"{row_pct.get('5% Reduced', 0):.1f}%")
    c3.metric("Zero Rated (0%)",    f"{row_pct.get('0% Zero Rated', 0):.1f}%")
    c4.metric("Total Sales",        f"£{pivot_chart.sum(axis=1).iloc[-1]:,.0f}")

    st.divider()

    # ── Line chart – % share ──────────────────────────────────────────────────
    st.subheader("% of Sales by VAT Category")

    fig = go.Figure()
    for cat in pivot_pct.columns:
        fig.add_trace(go.Scatter(
            x=list(pivot_pct.index),
            y=pivot_pct[cat].round(2),
            mode="lines+markers",
            name=cat,
            hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(
        height=380,
        margin=dict(l=0, r=0, t=12, b=0),
        xaxis=dict(showgrid=False, tickangle=-30),
        yaxis=dict(ticksuffix="%", range=[0, 105], showgrid=True),
        legend=dict(orientation="h", y=-0.25, x=0),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Bar chart – absolute £ ────────────────────────────────────────────────
    st.subheader("Absolute Sales (£) by VAT Category")

    fig2 = go.Figure()
    for cat in pivot_chart.columns:
        fig2.add_trace(go.Bar(
            x=list(pivot_chart.index),
            y=pivot_chart[cat].round(2),
            name=cat,
            hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>£%{{y:,.0f}}<extra></extra>",
        ))

    fig2.update_layout(
        barmode="stack",
        height=340,
        margin=dict(l=0, r=0, t=12, b=0),
        xaxis=dict(showgrid=False, tickangle=-30),
        yaxis=dict(tickprefix="£", showgrid=True),
        legend=dict(orientation="h", y=-0.25, x=0),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Tables & download ─────────────────────────────────────────────────────
    with st.expander("View data tables"):
        st.markdown("**% of sales**")
        st.dataframe(pivot_pct.style.format("{:.1f}%"), use_container_width=True)
        st.markdown("**Absolute sales (£)**")
        st.dataframe(pivot_chart.style.format("£{:,.2f}"), use_container_width=True)

    st.download_button(
        "Download % breakdown (CSV)",
        data=pivot_pct.reset_index().to_csv(index=False),
        file_name="vat_trends_pct.csv",
        mime="text/csv",
    )

    # ── Unmatched ASINs ───────────────────────────────────────────────────────
    if unmatched_log:
        with st.expander(f"⚠️ {len(unmatched_log)} unmatched ASINs (excluded from charts)"):
            st.caption("These ASINs were in the Amazon report but not found in your sheet.")
            st.dataframe(
                pd.DataFrame(unmatched_log, columns=["Month", "ASIN"]),
                use_container_width=True,
            )
