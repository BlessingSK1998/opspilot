"""One colour system and a little CSS to remove default-Streamlit clutter."""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from dashboard.helpers import CATEGORY_COLOURS

CSS = """
<style>
#MainMenu, footer, header [data-testid="stToolbar"] {visibility: hidden;}
.block-container {padding-top: 1.6rem; max-width: 1280px;}
h1 {font-size: 1.7rem !important; letter-spacing: -0.01em;}
h2, h3 {letter-spacing: -0.005em;}
.kpi {background:#fff;border:1px solid #E3E7ED;border-radius:12px;padding:14px 16px;height:100%;}
.kpi .label {font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;color:#5B6B7F;}
.kpi .value {font-size:1.85rem;font-weight:650;color:#1B2430;line-height:1.2;}
.kpi .hint {font-size:.76rem;color:#8A94A3;}
.chip {display:inline-block;padding:1px 9px;border-radius:999px;font-size:.76rem;font-weight:600;margin-right:4px;}
.muted {color:#8A94A3;}
.card {background:#fff;border:1px solid #E3E7ED;border-radius:12px;padding:14px 18px;margin-bottom:10px;}
.email {background:#fff;border:1px solid #E3E7ED;border-radius:10px;padding:12px 16px;font-size:.9rem;line-height:1.5;max-height:340px;overflow:auto;}
mark {background:#FFE9A8;padding:0 2px;border-radius:3px;}
.empty {text-align:center;color:#8A94A3;padding:48px 0;border:1px dashed #CBD2DC;border-radius:12px;background:#fff;}
</style>
"""

pio.templates["opspilot"] = go.layout.Template(layout=go.Layout(
    font={"family": "Inter, -apple-system, Segoe UI, sans-serif", "color": "#1B2430"}, colorway=CATEGORY_COLOURS,
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin={"l": 10, "r": 10, "t": 30, "b": 10},
    xaxis={"gridcolor": "#EEF1F5"}, yaxis={"gridcolor": "#EEF1F5"},
))  # fmt: skip
pio.templates.default = "opspilot"


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def kpi(label: str, value: str, hint: str = "") -> None:
    st.markdown(
        f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


def empty(message: str) -> None:
    st.markdown(f'<div class="empty">{message}</div>', unsafe_allow_html=True)
