import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
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

# ── Column config ─────────────────────────────────────────────────────────────
ASIN_COL_SHEET   = "ASIN"
VAT_COL_SHEET    = "VAT Code"
ASIN_COL_AMAZON  = "(Child) ASIN"
SALES_COL_AMAZON = "Ordered Product Sales"
TITLE_COL_AMAZON = "Title"          # product title in Amazon report
UNITS_COL_AMAZON = "Units Ordered"  # optional — used if present
FIXED_TAB        = "🧲 Profit Calculator - VAT 20%"

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_sheet_id(url: str):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def load_tab_as_df(sheet_id: str, tab_name: str):
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(tab_name)}"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df_raw = pd.read_csv(io.StringIO(r.text), header=None, dtype=str)
        # Find header row by scanning for "ASIN"
        header_idx = None
        for i, row in df_raw.iterrows():
            if row.astype(str).str.strip().str.upper().eq("ASIN").any():
                header_idx = i
                break
        if header_idx is None:
            st.error("Could not find a row containing 'ASIN' in the selected tab.")
            return None
        df_raw.columns = [
            str(h).strip() if pd.notna(h) and str(h).strip() not in ("", "nan") else f"_col_{i}"
            for i, h in enumerate(df_raw.iloc[header_idx])
        ]
        df = df_raw.iloc[header_idx + 1:].reset_index(drop=True)
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


def clean_sales(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(r"[£,\s]", "", regex=True)
        .str.replace(r"[^\d\.-]", "", regex=True),
        errors="coerce"
    ).fillna(0)


def try_parse_month(s: str):
    for fmt in ["%b %Y", "%B %Y", "%m/%Y", "%Y-%m", "%b_%Y", "%B_%Y", "%b%Y"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    return None


def sort_months(index):
    parsed = [try_parse_month(m) for m in index]
    if all(p is not None for p in parsed):
        return [index[i] for i in sorted(range(len(parsed)), key=lambda i: parsed[i])]
    return list(index)


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("Settings")
    st.divider()
    st.subheader("Google Sheet")
    st.caption("Share as **Anyone with the link → Viewer** first.")
    sheet_url = st.text_input("Sheet URL", placeholder="https://docs.google.com/spreadsheets/d/…")
    sheet_id  = extract_sheet_id(sheet_url) if sheet_url else None
    if sheet_url and not sheet_id:
        st.error("Could not find a Sheet ID in that URL.")
    st.divider()
    st.caption("Amazon UK · VAT sales trend tracker")


# ═════════════════════════════════════════════════════════════════════════════
# LOAD GOOGLE SHEET
# ═════════════════════════════════════════════════════════════════════════════
gsheet_df = None
vat_map   = {}   # { ASIN → "20% Standard" | "5% Reduced" | "0% Zero Rated" }

st.title("VAT Sales Trends")
st.caption("Upload your monthly Amazon UK business reports and track VAT split trends and SKU-level performance.")
st.divider()

if sheet_id:
    with st.spinner("Loading VAT catalogue from Google Sheet…"):
        gsheet_df = load_tab_as_df(sheet_id, FIXED_TAB)

    if gsheet_df is not None:
        missing = [c for c in [ASIN_COL_SHEET, VAT_COL_SHEET] if c not in gsheet_df.columns]
        if missing:
            available = "`, `".join(str(c) for c in gsheet_df.columns.tolist())
            st.warning(f"Column(s) not found: **{', '.join(missing)}**  \nAvailable: `{available}`")
        else:
            vat_map = {
                norm_asin(pd.Series([r[ASIN_COL_SHEET]]))[0]: map_vat_category(r[VAT_COL_SHEET])
                for _, r in gsheet_df.iterrows()
                if pd.notna(r[ASIN_COL_SHEET]) and str(r[ASIN_COL_SHEET]).strip() not in ("", "nan")
            }
            st.success(f"VAT catalogue loaded — **{len(vat_map):,}** ASINs mapped.")
            with st.expander("Preview VAT mapping"):
                st.dataframe(gsheet_df[[ASIN_COL_SHEET, VAT_COL_SHEET]].head(20), use_container_width=True)
else:
    st.info("Paste your Google Sheet URL in the sidebar to get started.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# UPLOAD REPORTS
# ═════════════════════════════════════════════════════════════════════════════
st.subheader("Monthly Amazon Business Reports")
st.caption("One file per month. Download from Seller Central → Reports → Business Reports → Detail Page Sales and Traffic by Child ASIN.")

uploaded_files = st.file_uploader(
    "Upload files", type=["csv", "xlsx", "xls"],
    accept_multiple_files=True, label_visibility="collapsed",
)

month_labels = {}
if uploaded_files:
    st.write("**Assign a month label to each file:**")
    cols = st.columns(min(len(uploaded_files), 4))
    for i, f in enumerate(uploaded_files):
        with cols[i % 4]:
            month_labels[f.name] = st.text_input(
                f.name, value=f.name.rsplit(".", 1)[0],
                key=f"lbl_{i}", placeholder="e.g. Jan 2025",
            )

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# PROCESS & DISPLAY
# ═════════════════════════════════════════════════════════════════════════════
if uploaded_files and not vat_map:
    st.info("Connect your Google Sheet in the sidebar to analyse the reports.")

if uploaded_files and vat_map:

    # ── Parse all uploaded files ──────────────────────────────────────────────
    all_rows      = []   # for trend aggregation (month × category)
    sku_rows      = []   # for SKU breakdown (one row per ASIN per month)
    unmatched_log = []
    progress      = st.progress(0, text="Processing…")

    for idx, f in enumerate(uploaded_files):
        month = month_labels.get(f.name, f.name)
        df    = parse_amazon_report(f)
        if df is None:
            continue

        missing_cols = [c for c in [ASIN_COL_AMAZON, SALES_COL_AMAZON] if c not in df.columns]
        if missing_cols:
            joined = "`, `".join(missing_cols)
            st.warning(f"**{f.name}** — columns not found: `{joined}`")
            continue

        df = df.copy()
        df["_ASIN"]  = norm_asin(df[ASIN_COL_AMAZON])
        df["_Sales"] = clean_sales(df[SALES_COL_AMAZON])
        df["_Units"] = clean_sales(df[UNITS_COL_AMAZON]) if UNITS_COL_AMAZON in df.columns else 0
        df["_Title"] = df[TITLE_COL_AMAZON].astype(str).str.strip() if TITLE_COL_AMAZON in df.columns else ""
        df["_VAT"]   = df["_ASIN"].map(vat_map).fillna("Unmatched")
        df["_Month"] = month

        unmatched_log.extend(
            [(month, a) for a in df[df["_VAT"] == "Unmatched"]["_ASIN"].unique()]
        )

        # Trend rows (aggregated)
        for cat, grp in df.groupby("_VAT"):
            all_rows.append({"Month": month, "VAT Category": cat, "Sales": grp["_Sales"].sum()})

        # SKU rows (per-ASIN)
        for _, row in df.iterrows():
            sku_rows.append({
                "Month":        row["_Month"],
                "ASIN":         row["_ASIN"],
                "Title":        row["_Title"],
                "VAT Category": row["_VAT"],
                "Sales":        row["_Sales"],
                "Units":        row["_Units"],
            })

        progress.progress((idx + 1) / len(uploaded_files), text=f"Processed: {month}")

    progress.empty()

    if not all_rows:
        st.error("No data could be processed.")
        st.stop()

    # ── Build trend pivot ─────────────────────────────────────────────────────
    df_trend = pd.DataFrame(all_rows)
    pivot    = df_trend.pivot_table(
        index="Month", columns="VAT Category", values="Sales", aggfunc="sum"
    ).fillna(0)

    sorted_months = sort_months(list(pivot.index))
    pivot         = pivot.loc[sorted_months]

    chart_cats  = [c for c in pivot.columns if c != "Unmatched"]
    pivot_chart = pivot[chart_cats]
    pivot_pct   = pivot_chart.div(pivot_chart.sum(axis=1), axis=0) * 100

    # ── Build SKU DataFrame ───────────────────────────────────────────────────
    df_sku = pd.DataFrame(sku_rows)
    df_sku = df_sku[df_sku["VAT Category"] != "Unmatched"].copy()

    # ═══════════════════════════════
    # TWO TABS
    # ═══════════════════════════════
    tab1, tab2 = st.tabs(["📈 Trends Overview", "🔍 SKU Breakdown"])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 — TRENDS OVERVIEW
    # ─────────────────────────────────────────────────────────────────────────
    with tab1:

        # Metric cards
        latest     = sorted_months[-1]
        prev       = sorted_months[-2] if len(sorted_months) >= 2 else None
        row_latest = pivot_pct.loc[latest]
        row_prev   = pivot_pct.loc[prev] if prev else None

        def delta_pp(cat):
            if row_prev is None:
                return None
            return f"{row_latest.get(cat, 0) - row_prev.get(cat, 0):+.1f} pp"

        st.subheader(f"Latest month — {latest}")
        if prev:
            st.caption(f"Δ vs {prev}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Standard VAT (20%)", f"{row_latest.get('20% Standard', 0):.1f}%",  delta=delta_pp("20% Standard"))
        c2.metric("Reduced VAT (5%)",   f"{row_latest.get('5% Reduced', 0):.1f}%",    delta=delta_pp("5% Reduced"))
        c3.metric("Zero Rated (0%)",    f"{row_latest.get('0% Zero Rated', 0):.1f}%", delta=delta_pp("0% Zero Rated"))

        total_latest = pivot_chart.sum(axis=1).iloc[-1]
        if len(pivot_chart) >= 2:
            total_diff  = total_latest - pivot_chart.sum(axis=1).iloc[-2]
            sign        = "+" if total_diff >= 0 else "-"
            total_delta = f"{sign}£{abs(total_diff):,.0f}"
        else:
            total_delta = None
        c4.metric("Total Sales", f"£{total_latest:,.0f}", delta=total_delta)

        st.divider()

        # Chart 1 — % share trend
        st.subheader("% Share of Sales by VAT Category")
        st.caption("How much of your total monthly revenue comes from each VAT category.")
        fig = go.Figure()
        for cat in pivot_pct.columns:
            fig.add_trace(go.Scatter(
                x=sorted_months, y=pivot_pct[cat].round(2),
                mode="lines+markers", name=cat,
                hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
            ))
        fig.update_layout(
            height=380, margin=dict(l=0, r=0, t=12, b=0),
            xaxis=dict(showgrid=False, tickangle=-30),
            yaxis=dict(ticksuffix="%", range=[0, 105], showgrid=True),
            legend=dict(orientation="h", y=-0.25, x=0),
            hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Chart 2 — MoM delta
        if len(pivot_pct) >= 2:
            st.subheader("Month-on-Month Change (percentage points)")
            st.caption("Green = gained share vs prior month · Red = lost share.")
            delta_df = pivot_pct.diff().dropna()
            fig_d = go.Figure()
            for cat in delta_df.columns:
                vals   = delta_df[cat].round(2).tolist()
                colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in vals]
                fig_d.add_trace(go.Bar(
                    x=list(delta_df.index), y=vals, name=cat,
                    marker_color=colors,
                    hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>%{{y:+.1f}} pp<extra></extra>",
                ))
            fig_d.add_hline(y=0, line_width=1, line_color="grey")
            fig_d.update_layout(
                barmode="group", height=340, margin=dict(l=0, r=0, t=12, b=0),
                xaxis=dict(showgrid=False, tickangle=-30),
                yaxis=dict(ticksuffix=" pp", showgrid=True, zeroline=False),
                legend=dict(orientation="h", y=-0.25, x=0),
                hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
            )
            st.plotly_chart(fig_d, use_container_width=True)

        # Chart 3 — Absolute £ stacked bar
        st.subheader("Absolute Sales (£) by VAT Category")
        fig2 = go.Figure()
        for cat in pivot_chart.columns:
            fig2.add_trace(go.Bar(
                x=sorted_months, y=pivot_chart[cat].round(2), name=cat,
                hovertemplate=f"<b>{cat}</b><br>%{{x}}<br>£%{{y:,.0f}}<extra></extra>",
            ))
        fig2.update_layout(
            barmode="stack", height=340, margin=dict(l=0, r=0, t=12, b=0),
            xaxis=dict(showgrid=False, tickangle=-30),
            yaxis=dict(tickprefix="£", showgrid=True),
            legend=dict(orientation="h", y=-0.25, x=0),
            plot_bgcolor="white", paper_bgcolor="white",
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Month-by-month summary table
        st.subheader("Month-by-Month Summary")
        summary_rows = []
        for i, month in enumerate(sorted_months):
            row = {"Month": month}
            for cat in pivot_pct.columns:
                pct_val = pivot_pct.loc[month, cat]
                row[f"{cat} (%)"] = f"{pct_val:.1f}%"
                if i > 0:
                    prev_m    = sorted_months[i - 1]
                    delta_val = pct_val - pivot_pct.loc[prev_m, cat]
                    arrow     = "▲" if delta_val > 0 else ("▼" if delta_val < 0 else "–")
                    row[f"{cat} Δ"] = f"{arrow} {abs(delta_val):.1f} pp"
                else:
                    row[f"{cat} Δ"] = "–"
            summary_rows.append(row)
        st.dataframe(pd.DataFrame(summary_rows).set_index("Month"), use_container_width=True)

        with st.expander("View raw data tables"):
            st.markdown("**% of sales**")
            st.dataframe(pivot_pct.style.format("{:.1f}%"), use_container_width=True)
            st.markdown("**Absolute sales (£)**")
            st.dataframe(pivot_chart.style.format("£{:,.2f}"), use_container_width=True)

        st.download_button(
            "Download % breakdown (CSV)",
            data=pivot_pct.reset_index().to_csv(index=False),
            file_name="vat_trends_pct.csv", mime="text/csv",
        )

        if unmatched_log:
            with st.expander(f"⚠️ {len(unmatched_log)} unmatched ASINs"):
                st.caption("Found in Amazon report but not in your sheet — excluded from charts.")
                st.dataframe(pd.DataFrame(unmatched_log, columns=["Month", "ASIN"]), use_container_width=True)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 — SKU BREAKDOWN
    # ─────────────────────────────────────────────────────────────────────────
    with tab2:
        st.subheader("SKU-Level Sales Breakdown")
        st.caption("Drill into individual ASINs — filter by VAT category and month, and see month-on-month sales changes per SKU.")

        # ── Filters ──────────────────────────────────────────────────────────
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            vat_filter = st.multiselect(
                "VAT Category",
                options=sorted(df_sku["VAT Category"].unique()),
                default=sorted(df_sku["VAT Category"].unique()),
            )
        with f_col2:
            month_filter = st.multiselect(
                "Month",
                options=sorted_months,
                default=sorted_months,
            )

        df_filtered = df_sku[
            df_sku["VAT Category"].isin(vat_filter) &
            df_sku["Month"].isin(month_filter)
        ].copy()

        if df_filtered.empty:
            st.warning("No data matches the selected filters.")
            st.stop()

        # ── Pivot: ASIN × Month sales ─────────────────────────────────────────
        sku_pivot = df_filtered.pivot_table(
            index=["ASIN", "Title", "VAT Category"],
            columns="Month",
            values="Sales",
            aggfunc="sum",
        ).fillna(0)

        # Sort months correctly
        available_months = [m for m in sorted_months if m in sku_pivot.columns]
        sku_pivot = sku_pivot[available_months]

        # ── Add total & MoM delta columns ─────────────────────────────────────
        sku_pivot["Total Sales"] = sku_pivot[available_months].sum(axis=1)

        if len(available_months) >= 2:
            last_m = available_months[-1]
            prev_m = available_months[-2]
            sku_pivot["Last Month (£)"]  = sku_pivot[last_m]
            sku_pivot["Prev Month (£)"]  = sku_pivot[prev_m]
            sku_pivot["MoM Change (£)"]  = sku_pivot[last_m] - sku_pivot[prev_m]
            sku_pivot["MoM Change (%)"]  = (
                (sku_pivot["MoM Change (£)"] / sku_pivot["Prev Month (£)"].replace(0, float("nan"))) * 100
            ).round(1)

        sku_pivot = sku_pivot.sort_values("Total Sales", ascending=False).reset_index()

        # ── Top SKUs bar chart ────────────────────────────────────────────────
        top_n   = min(20, len(sku_pivot))
        top_sku = sku_pivot.head(top_n).copy()
        top_sku["Label"] = top_sku["ASIN"] + (
            (" — " + top_sku["Title"].str[:40]) if top_sku["Title"].str.strip().ne("").any() else ""
        )

        st.subheader(f"Top {top_n} ASINs by Total Sales")
        fig_sku = px.bar(
            top_sku, x="Total Sales", y="Label",
            color="VAT Category", orientation="h",
            labels={"Total Sales": "Total Sales (£)", "Label": ""},
            hover_data={"Label": False, "ASIN": True, "VAT Category": True, "Total Sales": ":.2f"},
        )
        fig_sku.update_layout(
            height=max(400, top_n * 28),
            margin=dict(l=0, r=0, t=12, b=0),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(tickprefix="£", showgrid=True),
            legend=dict(orientation="h", y=-0.12, x=0),
            plot_bgcolor="white", paper_bgcolor="white",
        )
        fig_sku.update_traces(marker_line_width=0)
        st.plotly_chart(fig_sku, use_container_width=True)

        # ── MoM delta chart (top 20 by absolute change) ───────────────────────
        if len(available_months) >= 2 and "MoM Change (£)" in sku_pivot.columns:
            st.subheader(f"Month-on-Month Sales Change — {prev_m} → {last_m}")
            st.caption("How much each SKU's sales moved vs the previous month. Green = grew, Red = declined.")

            delta_top = sku_pivot.nlargest(20, "Total Sales").copy()
            delta_top["Label"] = delta_top["ASIN"] + (
                (" — " + delta_top["Title"].str[:35]) if delta_top["Title"].str.strip().ne("").any() else ""
            )
            delta_top["Color"] = delta_top["MoM Change (£)"].apply(
                lambda v: "#2ecc71" if v >= 0 else "#e74c3c"
            )
            delta_top = delta_top.sort_values("MoM Change (£)")

            fig_delta = go.Figure(go.Bar(
                x=delta_top["MoM Change (£)"].round(2),
                y=delta_top["Label"],
                orientation="h",
                marker_color=delta_top["Color"].tolist(),
                customdata=delta_top[["MoM Change (%)", "VAT Category"]].values,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Change: £%{x:,.0f}<br>"
                    "Change %: %{customdata[0]}%<br>"
                    "VAT: %{customdata[1]}<extra></extra>"
                ),
            ))
            fig_delta.add_vline(x=0, line_width=1, line_color="grey")
            fig_delta.update_layout(
                height=max(400, len(delta_top) * 28),
                margin=dict(l=0, r=0, t=12, b=0),
                xaxis=dict(tickprefix="£", showgrid=True, zeroline=False),
                yaxis=dict(showgrid=False),
                plot_bgcolor="white", paper_bgcolor="white",
            )
            st.plotly_chart(fig_delta, use_container_width=True)

        # ── Detailed table ────────────────────────────────────────────────────
        st.subheader("Full SKU Table")

        display_cols = ["ASIN", "Title", "VAT Category"] + available_months + ["Total Sales"]
        if "MoM Change (£)" in sku_pivot.columns:
            display_cols += ["MoM Change (£)", "MoM Change (%)"]

        display_df = sku_pivot[display_cols].copy()

        # Format £ columns
        money_cols = available_months + ["Total Sales"] + (
            ["MoM Change (£)"] if "MoM Change (£)" in display_df.columns else []
        )

        def colour_delta(val):
            if isinstance(val, (int, float)):
                color = "#d4edda" if val > 0 else ("#f8d7da" if val < 0 else "")
                return f"background-color: {color}"
            return ""

        styled = display_df.style.format(
            {c: "£{:,.2f}" for c in money_cols}
        )
        if "MoM Change (£)" in display_df.columns:
            try:
                styled = styled.map(colour_delta, subset=["MoM Change (£)", "MoM Change (%)"])
            except AttributeError:
                styled = styled.applymap(colour_delta, subset=["MoM Change (£)", "MoM Change (%)"])

        st.dataframe(styled, use_container_width=True, height=500)

        # ── Deep-Dive: Trend Analysis ─────────────────────────────────────────
        if len(available_months) >= 2:
            st.divider()
            st.subheader("Trend Analysis")
            st.caption("Analyse trends for individual ASINs or for an entire VAT category group.")

            mode = st.radio(
                "View by",
                options=["Individual ASINs", "VAT Category Group"],
                horizontal=True,
                key="trend_mode",
            )

            if mode == "Individual ASINs":
                # Build "ASIN — Title" labels for the dropdown
                asin_label_map = {
                    row["ASIN"]: f"{row['ASIN']}  —  {str(row['Title'])[:50]}" if str(row["Title"]).strip() not in ("", "nan") else row["ASIN"]
                    for _, row in sku_pivot.iterrows()
                }
                label_to_asin = {v: k for k, v in asin_label_map.items()}
                all_labels    = list(asin_label_map.values())

                chosen_labels = st.multiselect(
                    "Select ASIN(s)",
                    options=all_labels,
                    default=all_labels[:1],
                    key="asin_dd",
                    help="Search by ASIN or product name. Select one or more to compare.",
                )

                if not chosen_labels:
                    st.info("Select at least one ASIN above.")
                else:
                    chosen_asins = [label_to_asin[l] for l in chosen_labels]
                    selected_rows = sku_pivot[sku_pivot["ASIN"].isin(chosen_asins)]

                    fig_dd = go.Figure()
                    for _, row in selected_rows.iterrows():
                        label  = asin_label_map[row["ASIN"]]
                        sales  = [row.get(m, 0) for m in available_months]
                        fig_dd.add_trace(go.Scatter(
                            x=available_months, y=sales,
                            mode="lines+markers", name=label,
                            hovertemplate=f"<b>{label}</b><br>%{{x}}<br>£%{{y:,.2f}}<extra></extra>",
                        ))

                    fig_dd.update_layout(
                        height=360, margin=dict(l=0, r=0, t=12, b=0),
                        xaxis=dict(showgrid=False, tickangle=-30),
                        yaxis=dict(tickprefix="£", showgrid=True),
                        legend=dict(orientation="h", y=-0.28, x=0),
                        hovermode="x unified",
                        plot_bgcolor="white", paper_bgcolor="white",
                    )
                    st.plotly_chart(fig_dd, use_container_width=True)

                    # Mini delta table for selected ASINs
                    if len(available_months) >= 2:
                        last_m = available_months[-1]
                        prev_m = available_months[-2]
                        delta_rows = []
                        for _, row in selected_rows.iterrows():
                            last_val = row.get(last_m, 0)
                            prev_val = row.get(prev_m, 0)
                            change   = last_val - prev_val
                            pct      = (change / prev_val * 100) if prev_val else None
                            delta_rows.append({
                                "ASIN":           row["ASIN"],
                                "Title":          str(row["Title"])[:50],
                                "VAT Category":   row["VAT Category"],
                                f"{prev_m} (£)":  f"£{prev_val:,.2f}",
                                f"{last_m} (£)":  f"£{last_val:,.2f}",
                                "Change (£)":     f"{'▲' if change >= 0 else '▼'} £{abs(change):,.2f}",
                                "Change (%)":     f"{pct:+.1f}%" if pct is not None else "—",
                            })
                        st.dataframe(pd.DataFrame(delta_rows), use_container_width=True, hide_index=True)

            else:  # VAT Category Group
                vat_options   = sorted(df_sku["VAT Category"].unique())
                chosen_groups = st.multiselect(
                    "Select VAT Category Group(s)",
                    options=vat_options,
                    default=vat_options,
                    key="vat_group_dd",
                )

                if not chosen_groups:
                    st.info("Select at least one VAT category above.")
                else:
                    # Aggregate total sales per group per month
                    group_data = (
                        df_sku[df_sku["VAT Category"].isin(chosen_groups)]
                        .groupby(["VAT Category", "Month"])["Sales"]
                        .sum()
                        .reset_index()
                    )
                    group_pivot = group_data.pivot_table(
                        index="VAT Category", columns="Month", values="Sales", aggfunc="sum"
                    ).fillna(0)
                    group_pivot = group_pivot[[m for m in available_months if m in group_pivot.columns]]

                    # Line chart — absolute £ per group
                    fig_grp = go.Figure()
                    for grp in group_pivot.index:
                        fig_grp.add_trace(go.Scatter(
                            x=list(group_pivot.columns),
                            y=group_pivot.loc[grp].round(2).tolist(),
                            mode="lines+markers", name=grp,
                            hovertemplate=f"<b>{grp}</b><br>%{{x}}<br>£%{{y:,.0f}}<extra></extra>",
                        ))

                    fig_grp.update_layout(
                        height=360, margin=dict(l=0, r=0, t=12, b=0),
                        xaxis=dict(showgrid=False, tickangle=-30),
                        yaxis=dict(tickprefix="£", showgrid=True),
                        legend=dict(orientation="h", y=-0.25, x=0),
                        hovermode="x unified",
                        plot_bgcolor="white", paper_bgcolor="white",
                        title="Total Sales (£) per VAT Category Group",
                    )
                    st.plotly_chart(fig_grp, use_container_width=True)

                    # MoM delta table for groups
                    if len(available_months) >= 2:
                        last_m = available_months[-1]
                        prev_m = available_months[-2]
                        st.markdown(f"**Month-on-Month: {prev_m} → {last_m}**")
                        grp_delta_rows = []
                        for grp in group_pivot.index:
                            last_val = group_pivot.loc[grp, last_m] if last_m in group_pivot.columns else 0
                            prev_val = group_pivot.loc[grp, prev_m] if prev_m in group_pivot.columns else 0
                            change   = last_val - prev_val
                            pct      = (change / prev_val * 100) if prev_val else None
                            sku_count = df_sku[(df_sku["VAT Category"] == grp) & (df_sku["Month"] == last_m)]["ASIN"].nunique()
                            grp_delta_rows.append({
                                "VAT Category":      grp,
                                "ASINs in group":    sku_count,
                                f"{prev_m} (£)":     f"£{prev_val:,.0f}",
                                f"{last_m} (£)":     f"£{last_val:,.0f}",
                                "Change (£)":        f"{'▲' if change >= 0 else '▼'} £{abs(change):,.0f}",
                                "Change (%)":        f"{pct:+.1f}%" if pct is not None else "—",
                            })
                        st.dataframe(pd.DataFrame(grp_delta_rows), use_container_width=True, hide_index=True)

                    # How many ASINs contribute to each group this month?
                    st.markdown("**ASIN count per group per month**")
                    count_pivot = (
                        df_sku[df_sku["VAT Category"].isin(chosen_groups)]
                        .groupby(["VAT Category", "Month"])["ASIN"]
                        .nunique()
                        .reset_index()
                        .pivot_table(index="VAT Category", columns="Month", values="ASIN", aggfunc="sum")
                        .fillna(0)
                        .astype(int)
                    )
                    count_pivot = count_pivot[[m for m in available_months if m in count_pivot.columns]]
                    st.dataframe(count_pivot, use_container_width=True)

        # Download
        st.download_button(
            "Download SKU table (CSV)",
            data=display_df.to_csv(index=False),
            file_name="sku_breakdown.csv", mime="text/csv",
        )
