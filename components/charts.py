"""
components/charts.py — Plotly chart styling helpers and brand constants
=======================================================================
No Streamlit dependency.  Applies a consistent Power BI-inspired visual
theme to all Plotly figures used across the dashboard.

# PRODUCT-CANDIDATE: This entire module.
"""

import plotly.graph_objects as go

# ── Brand / rider colours ────────────────────────────────────────
DA77_COLOR = "#0078D4"   # Microsoft blue — DA77
JA52_COLOR = "#E74C3C"   # Red — JA52

# ── Corner-phase colours ─────────────────────────────────────────
PHASE_COLORS = {
    "PH1": "#C0392B",
    "PH2": "#E67E22",
    "PH3": "#F1C40F",
    "PH4": "#27AE60",
    "PH5": "#2980B9",
}

PHASE_LABELS = {
    "PH1": "PH1 Braking",
    "PH2": "PH2 Entry",
    "PH3": "PH3 Apex",
    "PH4": "PH4 Exit",
    "PH5": "PH5 Hi-Speed",
}

# ── Typography ───────────────────────────────────────────────────
CHART_FONT = dict(family="Arial, sans-serif", size=12, color="#111111")


def apply_chart_layout(fig: go.Figure, height: int = 300, title: str = "") -> go.Figure:
    """Apply the standard Power BI-style layout to a Plotly figure.

    Args:
        fig:    Plotly Figure to style (mutated in-place and returned).
        height: Chart height in pixels.
        title:  Optional chart title text.

    Returns:
        The same figure, for chaining.

    # PRODUCT-CANDIDATE
    """
    fig.update_layout(
        height=height,
        title=dict(
            text=title,
            font=dict(size=13, color="#222222", family="Arial, sans-serif"),
            x=0,
        ),
        font=CHART_FONT,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8F9FA",
        margin=dict(l=10, r=10, t=44, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1,
            font=dict(color="#111111", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        coloraxis_colorbar=dict(
            tickfont=dict(color="#111111"),
        ),
    )
    fig.update_xaxes(
        gridcolor="#E5E5E5",
        linecolor="#CCCCCC",
        tickfont=dict(color="#333333", size=11),
        title_font=dict(color="#333333"),
        zerolinecolor="#CCCCCC",
    )
    fig.update_yaxes(
        gridcolor="#E5E5E5",
        linecolor="#CCCCCC",
        tickfont=dict(color="#333333", size=11),
        title_font=dict(color="#333333"),
        zerolinecolor="#CCCCCC",
    )
    return fig
