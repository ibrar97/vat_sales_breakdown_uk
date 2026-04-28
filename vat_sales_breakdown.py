import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re
from datetime import datetime

# ─── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Amazon UK VAT Trends",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stApp { font-family: 'Inter', sans-serif; }
    .metric-card {
        background: white;
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border-left: 5px solid;
        margin-bottom: 8px;
    }
    .metric-card.vat20 { border-color: #FF9900; }
    .metric-card.vat5  { border-color: #146EB4; }
    .metric-card.vat0  { border-color: #2ECC71; }
    .metric-title { font-size: 13px; color: #6c757d; margin-bottom: 4px; }
    .metric-value { font-size: 28px; font-weight: 700; color: #1a1a2e; }
    .metric-sub   { font-size: 12px; color: #adb5bd; margin-top: 4px; }
    .header-band {
        background: linear-gradient(135deg, #232F3E 0%, #146EB4 100%);
        padding: 28px 32px;
        border-radius: 14px;
        color: white;
        margin-bottom: 24px;
    }
    .header-band h1 { font-size: 26px; font-weight: 700; margin: 0; }
    .header-band p  { font-size: 14px; opacity: 0.8; margin: 6px 0 0; }
    .tip-box {
        background: #e8f4fd;
        border: 1px solid #90cdf4;
        border-radius: 8px;
        padding: 12px 16px;
        font-size: 13px;
        color: #2b6cb0;
        margin-bottom: 12px;
    }
    .stSidebar { background: #232F3E !important; }
</style>
""", unsafe_allow_html=True)

# ─── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-band">
  <h1>📊 Amazon UK VAT Sales Trends</h1>
  <p>Upload monthly business reports · Match ASINs to your VAT catalogue · Track 20% / 5% / 0% splits over time</p>
</div>
""", unsafe_allow_html=True)

# ─── Helper: Extract Sheet ID ────────────────────────────────────────────────────
def extract_sheet_id(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None

# ─── Helper: Load Google Sheet tab as DataFrame ──────────────────────────────────
def load_gsheet(sheet_id: str, tab_name: str) -> pd.DataFrame | None:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab_name)}"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # Drop fully-empty columns/rows that Sheets sometimes exports
        df = df.dropna(how="all", axis=1).dropna(how="all", axis=0)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        st.error(f"❌ Could not load Google Sheet: {e}")
        return None

# ─── Helper: Parse Amazon Business Report ───────────────────────────────────────
def parse_amazon_report(file, month_label: str) -> pd.DataFrame | None:
    try:
        name = file.name.lower()
        if name.endswith(".csv"):
            raw = pd.read_csv(file, encoding="utf-8-sig")
        else:
            raw = pd.read_excel(file)
        raw.columns = raw.columns.str.strip()
        return raw
    except Exception as e:
        st.error(f"❌ Could not parse {file.name}: {e}")
        return None

# ─── Helper: Normalise ASIN column ──────────────────────────────────────────────
def norm_asin(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()

# ─── Helper: Map VAT label to category ──────────────────────────────────────────
def map_vat_category(label: str) -> str:
    l = str(label).strip().lower()
    if any(x in l for x in ["20", "standard", "std", "s"]):
        return "20% Standard"
    if any(x in l for x in ["5", "reduced", "r"]):
        return "5% Reduced"
    if any(x in l for x in ["0", "zero", "exempt", "z", "free"]):
        return "0% Zero Rated"
    return "Unknown"

# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR  – Configuration
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=120)
    st.markdown("---")
    st.markdown("### 🔗 Google Sheet URL")

    st.markdown('<div class="tip-box">Share your sheet with <b>Anyone with the link → Viewer</b> before pasting the URL.</div>', unsafe_allow_html=True)

    sheet_url = st.text_input(
        "Google Sheet URL",
        placeholder="https://docs.google.com/spreadsheets/d/…",
        help="Paste the full URL from your browser address bar.",
    )

    # ── Static config (same for all team members) ────────────────────────────
    tab_name        = "Profit Calculator - VAT 20%"
    asin_col        = "ASIN"
    vat_col         = "VAT Code"
    sales_col       = "Ordered Product Sales"
    asin_col_amazon = "(Child) ASIN"

    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.caption("Built for Amazon UK sellers · VAT trend analytics")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN  – Google Sheet preview
# ═══════════════════════════════════════════════════════════════════════════════
gsheet_df = None
vat_map = {}

if sheet_url and tab_name and asin_col and vat_col:
    sheet_id = extract_sheet_id(sheet_url)
    if not sheet_id:
        st.error("❌ Couldn't find a Sheet ID in that URL. Make sure it's the full Google Sheets URL.")
    else:
        with st.spinner("Loading your Google Sheet…"):
            gsheet_df = load_gsheet(sheet_id, tab_name)

        if gsheet_df is not None:
            # Validate columns exist
            missing = [c for c in [asin_col, vat_col] if c not in gsheet_df.columns]
            if missing:
                st.warning(
                    f"⚠️ Column(s) not found in sheet: **{', '.join(missing)}**\n\n"
                    f"Available columns: `{'`, `'.join(gsheet_df.columns.tolist())}`"
                )
            else:
                # Build VAT map  { ASIN → "20% Standard" | "5% Reduced" | "0% Zero Rated" }
                vat_map = {
                    norm_asin(pd.Series([row[asin_col]]))[0]: map_vat_category(row[vat_col])
                    for _, row in gsheet_df.iterrows()
                }
                st.success(f"✅ Loaded **{len(vat_map):,}** ASINs from your Google Sheet")
                with st.expander("Preview VAT catalogue (first 20 rows)"):
                    st.dataframe(gsheet_df[[asin_col, vat_col]].head(20), use_container_width=True)
else:
    st.info("👈 Fill in the **Google Sheet Config** in the sidebar to link your VAT catalogue.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN  – Upload Reports
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## 📁 Upload Monthly Amazon Business Reports")
st.markdown("Upload one **or more** monthly reports. Each file = one month. Name the files clearly (e.g. `Jan_2025.csv`) or use the month picker below.")

uploaded_files = st.file_uploader(
    "Amazon Business Reports (CSV or Excel)",
    type=["csv", "xlsx", "xls"],
    accept_multiple_files=True,
    help="Download from Seller Central → Business Reports → Detail Page Sales and Traffic by ASIN",
)

# ─── Month labelling ─────────────────────────────────────────────────────────
month_labels = {}
if uploaded_files:
    st.markdown("### 📅 Assign a month to each file")
    cols = st.columns(min(len(uploaded_files), 3))
    for i, f in enumerate(uploaded_files):
        with cols[i % 3]:
            label = st.text_input(
                f"`{f.name}`",
                value=f.name.replace(".csv", "").replace(".xlsx", "").replace(".xls", ""),
                key=f"month_{i}",
                placeholder="e.g. Jan 2025",
            )
            month_labels[f.name] = label

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN  – Process & Chart
# ═══════════════════════════════════════════════════════════════════════════════
if uploaded_files and vat_map and sales_col and asin_col_amazon:
    if st.button("🚀 Generate VAT Trends Chart", type="primary", use_container_width=True):

        results = []   # list of dicts: { month, vat_cat, sales }
        unmatched_log = []

        progress = st.progress(0, text="Processing files…")

        for idx, f in enumerate(uploaded_files):
            month = month_labels.get(f.name, f.name)
            df = parse_amazon_report(f, month)
            if df is None:
                continue

            # Validate columns
            missing_cols = [c for c in [asin_col_amazon, sales_col] if c not in df.columns]
            if missing_cols:
                st.warning(
                    f"⚠️ **{f.name}**: Column(s) not found: `{'`, `'.join(missing_cols)}`\n\n"
                    f"Available: `{'`, `'.join(df.columns.tolist())}`"
                )
                continue

            df = df[[asin_col_amazon, sales_col]].copy()
            df.columns = ["ASIN", "Sales"]

            # Clean sales column (remove £, commas)
            df["Sales"] = (
                df["Sales"]
                .astype(str)
                .str.replace(r"[£,\s]", "", regex=True)
                .str.replace(r"[^\d\.-]", "", regex=True)
            )
            df["Sales"] = pd.to_numeric(df["Sales"], errors="coerce").fillna(0)
            df["ASIN"] = norm_asin(df["ASIN"])

            # Map VAT
            df["VAT Category"] = df["ASIN"].map(vat_map).fillna("Unmatched")

            # Log unmatched
            unmatched = df[df["VAT Category"] == "Unmatched"]["ASIN"].unique().tolist()
            unmatched_log.extend([(month, a) for a in unmatched])

            # Aggregate
            for cat, grp in df.groupby("VAT Category"):
                results.append({
                    "Month": month,
                    "VAT Category": cat,
                    "Sales": grp["Sales"].sum(),
                })

            progress.progress((idx + 1) / len(uploaded_files), text=f"Processed {month}…")

        progress.empty()

        if not results:
            st.error("No data could be processed. Check column names and file formats.")
        else:
            # ── Build pivot ──────────────────────────────────────────────────
            df_results = pd.DataFrame(results)
            pivot = df_results.pivot_table(
                index="Month", columns="VAT Category", values="Sales", aggfunc="sum"
            ).fillna(0)

            # Try to sort months chronologically if they look like dates
            def try_parse_month(s):
                for fmt in ["%b %Y", "%B %Y", "%m/%Y", "%Y-%m", "%b_%Y", "%B_%Y"]:
                    try:
                        return datetime.strptime(s.strip(), fmt)
                    except:
                        pass
                return None

            parsed = [try_parse_month(m) for m in pivot.index]
            if all(p is not None for p in parsed):
                pivot = pivot.iloc[[parsed.index(p) for p in sorted(parsed)]]

            # ── Percentage pivot ──────────────────────────────────────────────
            pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100

            # ── Summary metrics ──────────────────────────────────────────────
            st.markdown("## 📈 Results")
            latest_month = pivot_pct.index[-1]
            row = pivot_pct.loc[latest_month]

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                v20 = row.get("20% Standard", 0)
                st.markdown(f"""
                <div class="metric-card vat20">
                  <div class="metric-title">Standard VAT (20%)</div>
                  <div class="metric-value">{v20:.1f}%</div>
                  <div class="metric-sub">Latest month: {latest_month}</div>
                </div>""", unsafe_allow_html=True)
            with col2:
                v5 = row.get("5% Reduced", 0)
                st.markdown(f"""
                <div class="metric-card vat5">
                  <div class="metric-title">Reduced VAT (5%)</div>
                  <div class="metric-value">{v5:.1f}%</div>
                  <div class="metric-sub">Latest month: {latest_month}</div>
                </div>""", unsafe_allow_html=True)
            with col3:
                v0 = row.get("0% Zero Rated", 0)
                st.markdown(f"""
                <div class="metric-card vat0">
                  <div class="metric-title">Zero Rated (0%)</div>
                  <div class="metric-value">{v0:.1f}%</div>
                  <div class="metric-sub">Latest month: {latest_month}</div>
                </div>""", unsafe_allow_html=True)
            with col4:
                total_sales = pivot.sum(axis=1).iloc[-1]
                st.markdown(f"""
                <div class="metric-card" style="border-color:#6c757d;">
                  <div class="metric-title">Total Sales (latest month)</div>
                  <div class="metric-value">£{total_sales:,.0f}</div>
                  <div class="metric-sub">Latest month: {latest_month}</div>
                </div>""", unsafe_allow_html=True)

            # ── Trend chart (% of sales) ──────────────────────────────────────
            COLOURS = {
                "20% Standard": (255, 153,   0),
                "5% Reduced":   ( 20, 110, 180),
                "0% Zero Rated":( 46, 204, 113),
                "Unknown":      (173, 181, 189),
                "Unmatched":    (231,  76,  60),
            }

            def hex_colour(rgb): return "#{:02X}{:02X}{:02X}".format(*rgb)
            def rgba_colour(rgb, a=0.13): return "rgba({},{},{},{})".format(*rgb, a)

            fig = go.Figure()
            for cat in pivot_pct.columns:
                if cat in ("Unmatched",):
                    continue
                rgb = COLOURS.get(cat, (136, 136, 136))
                fig.add_trace(go.Scatter(
                    x=list(pivot_pct.index),
                    y=pivot_pct[cat].round(2),
                    mode="lines+markers",
                    name=cat,
                    line=dict(color=hex_colour(rgb), width=3),
                    marker=dict(size=8, line=dict(width=2, color="white")),
                    fill="tonexty" if cat != pivot_pct.columns[0] else "tozeroy",
                    fillcolor=rgba_colour(rgb),
                    hovertemplate=f"<b>{cat}</b><br>Month: %{{x}}<br>Share: %{{y:.1f}}%<extra></extra>",
                ))

            fig.update_layout(
                title=dict(text="VAT Category % of Sales Over Time", font=dict(size=18)),
                xaxis=dict(title="Month", showgrid=False, tickangle=-30),
                yaxis=dict(title="% of Total Sales", range=[0, 105], ticksuffix="%", showgrid=True, gridcolor="#f0f0f0"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="white",
                paper_bgcolor="white",
                height=480,
                margin=dict(l=40, r=20, t=80, b=60),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Absolute Sales chart ──────────────────────────────────────────
            fig2 = go.Figure()
            for cat in pivot.columns:
                if cat in ("Unmatched",):
                    continue
                rgb2 = COLOURS.get(cat, (136, 136, 136))
                fig2.add_trace(go.Bar(
                    x=list(pivot.index),
                    y=pivot[cat].round(2),
                    name=cat,
                    marker_color=hex_colour(rgb2),
                    hovertemplate=f"<b>{cat}</b><br>Month: %{{x}}<br>Sales: £%{{y:,.0f}}<extra></extra>",
                ))

            fig2.update_layout(
                title=dict(text="Absolute Sales by VAT Category (£)", font=dict(size=18)),
                barmode="stack",
                xaxis=dict(title="Month", showgrid=False, tickangle=-30),
                yaxis=dict(title="Sales (£)", tickprefix="£", showgrid=True, gridcolor="#f0f0f0"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="white",
                paper_bgcolor="white",
                height=420,
                margin=dict(l=40, r=20, t=80, b=60),
            )
            st.plotly_chart(fig2, use_container_width=True)

            # ── Data table ───────────────────────────────────────────────────
            with st.expander("📋 View data table"):
                st.markdown("**% of Sales by VAT Category**")
                st.dataframe(pivot_pct.style.format("{:.1f}%"), use_container_width=True)
                st.markdown("**Absolute Sales (£) by VAT Category**")
                st.dataframe(pivot.style.format("£{:,.2f}"), use_container_width=True)

            # ── Download ─────────────────────────────────────────────────────
            csv_out = pivot_pct.reset_index().to_csv(index=False)
            st.download_button(
                "⬇️ Download % breakdown as CSV",
                data=csv_out,
                file_name="vat_trends_percentage.csv",
                mime="text/csv",
            )

            # ── Unmatched ASINs warning ───────────────────────────────────────
            if unmatched_log:
                with st.expander(f"⚠️ {len(unmatched_log)} unmatched ASINs (not found in your Google Sheet)"):
                    unmatched_df = pd.DataFrame(unmatched_log, columns=["Month", "ASIN"])
                    st.dataframe(unmatched_df, use_container_width=True)
                    st.caption("These ASINs were found in the Amazon report but had no VAT mapping in your sheet. They are excluded from the charts above.")

elif uploaded_files and not vat_map:
    st.warning("⚠️ Please connect your Google Sheet in the sidebar first so ASINs can be matched to VAT categories.")
elif not uploaded_files and vat_map:
    st.info("📂 Google Sheet loaded! Now upload your monthly Amazon business report(s) above.")
else:
    st.markdown("""
    ### 🚀 Getting Started

    **Step 1** – Paste your Google Sheet URL in the sidebar and configure the column names.

    **Step 2** – Upload one or more Amazon Business Reports (CSV or Excel).
    > Download from: *Seller Central → Reports → Business Reports → Detail Page Sales and Traffic by Child ASIN*

    **Step 3** – Click **Generate VAT Trends Chart**.
    """)
