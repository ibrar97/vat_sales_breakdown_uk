import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VAT Sales Trends",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Material Design – plain white, no colours ─────────────────────────────────
st.markdown("""
<style>
    html, body, [class*="css"] { font-family: 'Roboto', 'Segoe UI', sans-serif; }
    .stApp { background: #ffffff; }

    [data-testid="stSidebar"] {
        background: #fafafa;
        border-right: 1px solid #e0e0e0;
    }
    [data-testid="stSidebar"] * { color: #212121 !important; }

    .block-container { padding-top: 2rem; padding-bottom: 2rem; }

    .page-title {
        font-size: 22px;
        font-weight: 500;
        color: #212121;
        letter-spacing: 0.01em;
        margin-bottom: 4px;
    }
    .page-subtitle {
        font-size: 13px;
        color: #757575;
        margin-bottom: 24px;
    }
    .md-divider {
        border: none;
        border-top: 1px solid #e0e0e0;
        margin: 20px 0;
    }
    .md-card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        padding: 20px 24px;
        margin-bottom: 8px;
    }
    .md-card-label {
        font-size: 11px;
        font-weight: 500;
        color: #757575;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
    }
    .md-card-value {
        font-size: 32px;
        font-weight: 300;
        color: #212121;
        line-height: 1;
    }
    .md-info {
        background: #fafafa;
        border: 1px solid #e0e0e0;
        border-radius: 4px;
        padding: 12px 16px;
        font-size: 13px;
        color: #616161;
        margin-bottom: 12px;
    }
    .section-label {
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #9e9e9e;
        margin-bottom: 8px;
        margin-top: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_sheet_id(url: str):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def get_sheet_tabs(sheet_id: str):
    """Fetch all tab names via the Google Sheets JSON feed."""
    feed_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/feed/worksheets?alt=json"
    try:
        r = requests.get(feed_url, timeout=10)
        if r.status_code == 200:
            entries = r.json().get("feed", {}).get("entry", [])
            return [e["title"]["$t"] for e in entries]
    except Exception:
        pass
    return []


def load_tab_as_df(sheet_id: str, tab_name: str, header_row: int = 2):
    """Download a tab as CSV and parse with given 0-indexed header row."""
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&sheet={requests.utils.quote(tab_name)}"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), header=header_row)
        df = df.dropna(how="all", axis=1).dropna(how="all", axis=0)
        df.columns = df.columns.str.strip()
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


# ── Static column names (hardcoded, same for everyone) ────────────────────────
ASIN_COL_SHEET   = "ASIN"
VAT_COL_SHEET    = "VAT Code"
ASIN_COL_AMAZON  = "(Child) ASIN"
SALES_COL_AMAZON = "Ordered Product Sales"
SHEET_HEADER_ROW = 2       # 0-indexed → row 3 in the spreadsheet

# Monochrome chart palette
MONO = ["#212121", "#757575", "#bdbdbd", "#e0e0e0"]

# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="section-label">Google Sheet</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="md-info">Share your sheet as <b>Anyone with the link → Viewer</b> first.</div>',
        unsafe_allow_html=True,
    )

    sheet_url  = st.text_input("Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/…", label_visibility="visible")
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

            st.markdown('<div class="section-label">Select tab</div>', unsafe_allow_html=True)
            if sheet_tabs:
                tab_name = st.selectbox("Tab", options=sheet_tabs, label_visibility="collapsed")
            else:
                st.caption("Could not fetch tabs automatically — make sure the sheet is shared publicly.")
                tab_name = st.text_input("Tab name", placeholder="e.g. Profit Calculator - VAT 20%")

    st.markdown('<hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0">', unsafe_allow_html=True)
    st.caption("Amazon UK · VAT sales trend tracker")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="page-title">VAT Sales Trends</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-subtitle">Match your Amazon UK business reports against your VAT catalogue and track 20% / 5% / 0% splits over time.</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="md-divider">', unsafe_allow_html=True)

# ── Step 1: Load the selected sheet tab ──────────────────────────────────────
gsheet_df = None
vat_map   = {}

if sheet_id and tab_name:
    with st.spinner(f"Loading '{tab_name}'…"):
        gsheet_df = load_tab_as_df(sheet_id, tab_name, header_row=SHEET_HEADER_ROW)

    if gsheet_df is not None:
        missing = [c for c in [ASIN_COL_SHEET, VAT_COL_SHEET] if c not in gsheet_df.columns]
        if missing:
            st.warning(
                f"Column(s) not found: **{', '.join(missing)}**  \n"
                f"Columns available: `{'`, `'.join(gsheet_df.columns.tolist())}`"
            )
        else:
            vat_map = {
                norm_asin(pd.Series([r[ASIN_COL_SHEET]]))[0]: map_vat_category(r[VAT_COL_SHEET])
                for _, r in gsheet_df.iterrows()
                if pd.notna(r[ASIN_COL_SHEET])
            }
            st.success(f"Sheet loaded — {len(vat_map):,} ASINs mapped.")
            with st.expander("Preview mapping (first 20 rows)"):
                st.dataframe(gsheet_df[[ASIN_COL_SHEET, VAT_COL_SHEET]].head(20), use_container_width=True)
else:
    st.markdown(
        '<div class="md-info">Paste your Google Sheet URL in the sidebar to get started.</div>',
        unsafe_allow_html=True,
    )

st.markdown('<hr class="md-divider">', unsafe_allow_html=True)

# ── Step 2: Upload Amazon reports ─────────────────────────────────────────────
st.markdown('<div class="section-label">Monthly Amazon Business Reports</div>', unsafe_allow_html=True)
st.caption("One file per month (CSV or Excel). Download from Seller Central → Reports → Business Reports → Detail Page Sales and Traffic by Child ASIN.")

uploaded_files = st.file_uploader(
    "Upload files",
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

month_labels = {}
if uploaded_files:
    st.markdown('<div class="section-label">Month labels</div>', unsafe_allow_html=True)
    cols = st.columns(min(len(uploaded_files), 4))
    for i, f in enumerate(uploaded_files):
        with cols[i % 4]:
            month_labels[f.name] = st.text_input(
                f.name,
                value=f.name.rsplit(".", 1)[0],
                key=f"lbl_{i}",
                placeholder="e.g. Jan 2025",
            )

st.markdown('<hr class="md-divider">', unsafe_allow_html=True)

# ── Step 3: Generate ─────────────────────────────────────────────────────────
ready = bool(uploaded_files and vat_map)

run = st.button("Generate trends", type="primary", disabled=not ready)
if not ready and uploaded_files and not vat_map:
    st.caption("Connect your Google Sheet in the sidebar to enable this.")

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
            st.warning(
                f"**{f.name}** — columns not found: `{'`, `'.join(missing_cols)}`  \n"
                f"Available: `{'`, `'.join(df.columns.tolist())}`"
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
        st.error("No data could be processed. Check that the column names in your report match the expected format.")
        st.stop()

    # ── Pivot tables ──────────────────────────────────────────────────────────
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

    st.markdown(f'<div class="section-label">Latest month — {latest}</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    for col, label, val in [
        (c1, "Standard VAT (20%)", f"{row_pct.get('20% Standard', 0):.1f}%"),
        (c2, "Reduced VAT (5%)",   f"{row_pct.get('5% Reduced', 0):.1f}%"),
        (c3, "Zero Rated (0%)",    f"{row_pct.get('0% Zero Rated', 0):.1f}%"),
        (c4, "Total Sales",        f"£{pivot_chart.sum(axis=1).iloc[-1]:,.0f}"),
    ]:
        with col:
            st.markdown(
                f'<div class="md-card">'
                f'<div class="md-card-label">{label}</div>'
                f'<div class="md-card-value">{val}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Line chart – % share ──────────────────────────────────────────────────
    st.markdown('<div class="section-label" style="margin-top:28px">% of sales by VAT category</div>', unsafe_allow_html=True)

    fig = go.Figure()
    for i, cat in enumerate(pivot_pct.columns):
        colour = MONO[i % len(MONO)]
        fig.add_trace(go.Scatter(
            x=list(pivot_pct.index),
            y=pivot_pct[cat].round(2),
            mode="lines+markers",
            name=cat,
            line=dict(color=colour, width=2),
            marker=dict(size=6, color=colour),
            hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
        ))

    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white",
        height=360,
        margin=dict(l=0, r=0, t=12, b=0),
        xaxis=dict(showgrid=False, tickangle=-30, linecolor="#e0e0e0",
                   tickfont=dict(size=12, color="#616161")),
        yaxis=dict(ticksuffix="%", range=[0, 105], showgrid=True, gridcolor="#f5f5f5",
                   tickfont=dict(size=12, color="#616161"), zeroline=False),
        legend=dict(orientation="h", y=-0.22, x=0,
                    font=dict(size=12, color="#424242"),
                    bgcolor="white", bordercolor="#e0e0e0", borderwidth=1),
        hovermode="x unified",
        font=dict(family="Roboto, Segoe UI, sans-serif"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Bar chart – absolute £ ────────────────────────────────────────────────
    st.markdown('<div class="section-label" style="margin-top:8px">Absolute sales (£) by VAT category</div>', unsafe_allow_html=True)

    fig2 = go.Figure()
    for i, cat in enumerate(pivot_chart.columns):
        colour = MONO[i % len(MONO)]
        fig2.add_trace(go.Bar(
            x=list(pivot_chart.index),
            y=pivot_chart[cat].round(2),
            name=cat,
            marker_color=colour,
            hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>£%{{y:,.0f}}<extra></extra>",
        ))

    fig2.update_layout(
        barmode="stack",
        plot_bgcolor="white", paper_bgcolor="white",
        height=320,
        margin=dict(l=0, r=0, t=12, b=0),
        xaxis=dict(showgrid=False, tickangle=-30, linecolor="#e0e0e0",
                   tickfont=dict(size=12, color="#616161")),
        yaxis=dict(tickprefix="£", showgrid=True, gridcolor="#f5f5f5",
                   tickfont=dict(size=12, color="#616161"), zeroline=False),
        legend=dict(orientation="h", y=-0.22, x=0,
                    font=dict(size=12, color="#424242"),
                    bgcolor="white", bordercolor="#e0e0e0", borderwidth=1),
        font=dict(family="Roboto, Segoe UI, sans-serif"),
    )
    st.plotly_chart(fig2, use_container_width=True)

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
        with st.expander(f"{len(unmatched_log)} unmatched ASINs (excluded from charts)"):
            st.caption("These ASINs were in the Amazon report but not found in your sheet.")
            st.dataframe(
                pd.DataFrame(unmatched_log, columns=["Month", "ASIN"]),
                use_container_width=True,
            )
