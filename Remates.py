import os
from urllib.parse import urlparse, parse_qs

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import ConnectionPatch

# imports para Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except Exception:
    HAS_GSPREAD = False

st.set_page_config(page_title="Remates por Fase", layout="wide")

# ---------- CONFIG ----------
SHEET_URL = "https://docs.google.com/spreadsheets/d/1H5BM8PWxqZZ5V6WKImTdKA6f6OsReQZSUWIJcf7ykEY/edit?gid=0#gid=0"
MAIN_TEAM_NAME = "Tigres"
LOGO_DIR = "."

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

# ---------- Helpers ----------
def extract_sheet_key(url_or_id: str) -> str:
    if not url_or_id:
        return None
    if "/" not in url_or_id and len(url_or_id) > 10:
        return url_or_id
    try:
        parts = url_or_id.split("/")
        if "d" in parts:
            return parts[parts.index("d") + 1]
    except Exception:
        pass
    parsed = urlparse(url_or_id)
    p = parsed.path
    if "/d/" in p:
        return p.split("/d/")[1].split("/")[0]
    return None

def extract_gid(url: str, default: int = 0) -> int:
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        gid_vals = qs.get("gid")
        if gid_vals:
            return int(gid_vals[0])
    except Exception:
        pass
    try:
        frag = url.split('#')[-1]
        if frag and "gid=" in frag:
            for part in frag.split('&'):
                if part.startswith("gid="):
                    return int(part.split("=", 1)[1])
    except Exception:
        pass
    return default

@st.cache_data
def load_via_csv_export(sheet_url: str):
    key = extract_sheet_key(sheet_url)
    if not key:
        raise ValueError("No se pudo extraer el sheet id de la URL.")
    gid = extract_gid(sheet_url, default=0)
    export_url = f"https://docs.google.com/spreadsheets/d/{key}/export?format=csv&gid={gid}"
    return pd.read_csv(export_url)

def client_from_service_account_file(path: str):
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)

def client_from_service_account_info(info: dict):
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def open_worksheet_by_url(client, url: str):
    try:
        sh = client.open_by_url(url)
    except Exception:
        key = extract_sheet_key(url)
        if not key:
            raise
        sh = client.open_by_key(key)
    try:
        ws = sh.worksheet("Varonil")
    except Exception:
        ws = sh.get_worksheet(0)
    return ws

def find_column_exact_or_similar(df_columns, target_name):
    target_low = target_name.lower().strip()
    for c in df_columns:
        if c.lower().strip() == target_low:
            return c
    for c in df_columns:
        if target_low in c.lower().strip():
            return c
    return None

def sort_mixed_values(values):
    vals = [str(v).strip() for v in values]
    numeric_vals = []
    non_numeric_vals = []
    for v in vals:
        if v.isdigit():
            numeric_vals.append(int(v))
        else:
            non_numeric_vals.append(v)
    return [str(x) for x in sorted(numeric_vals)] + sorted(non_numeric_vals, key=lambda x: x.lower())

def jornada_key(x):
    s = str(x).strip()
    if s.isdigit():
        return (0, int(s))
    return (1, s.lower())

def format_pct(pct):
    if pct >= 10:
        return f"{pct:.0f}%"
    if pct >= 1:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"

def format_metric(x):
    return f"{x:.2f}"

def get_metric_label(selected_view: str):
    return "xGC" if selected_view == "Rival" else "xG"

def get_metric_total_label(selected_view: str):
    return "xGC acumulado" if selected_view == "Rival" else "xG acumulado"

def build_phase_table(df_filtered, main_col, xg_col):
    if df_filtered.empty:
        return pd.DataFrame(columns=["Fase", "Conteo", "xG"])
    return (
        df_filtered
        .groupby(main_col, dropna=False)
        .agg(
            Conteo=(main_col, "size"),
            xG=(xg_col, "sum")
        )
        .reset_index()
        .rename(columns={main_col: "Fase"})
        .sort_values(["Conteo", "xG"], ascending=[False, False])
        .reset_index(drop=True)
    )

def build_break_table(df_filtered, main_col, sub_col, xg_col, selected_phase):
    rows_target = df_filtered[df_filtered[main_col] == selected_phase].copy()

    if rows_target.empty:
        df_break = pd.DataFrame(columns=["Concepto", "Conteo", "xG"])
        return rows_target, df_break

    df_break = (
        rows_target
        .groupby(sub_col, dropna=False)
        .agg(
            Conteo=(sub_col, "size"),
            xG=(xg_col, "sum")
        )
        .reset_index()
        .rename(columns={sub_col: "Concepto"})
        .sort_values(["Conteo", "xG"], ascending=[False, False])
        .reset_index(drop=True)
    )

    if df_break.empty:
        df_break = pd.DataFrame({
            "Concepto": ["Sin detalle"],
            "Conteo": [len(rows_target)],
            "xG": [rows_target[xg_col].sum()]
        })

    return rows_target, df_break

def is_light_color(color):
    r, g, b, *_ = color
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance > 0.6

def text_color_for_bar(color):
    return "black" if is_light_color(color) else "white"

def distribute_positions(items, min_gap=0.12, lower=-0.96, upper=0.96):
    if not items:
        return items

    items = sorted(items, key=lambda d: d["y"])
    items[0]["y_adj"] = min(max(items[0]["y"], lower), upper)

    for i in range(1, len(items)):
        items[i]["y_adj"] = max(items[i]["y"], items[i - 1]["y_adj"] + min_gap)

    overflow = items[-1]["y_adj"] - upper
    if overflow > 0:
        for item in items:
            item["y_adj"] -= overflow

    for i in range(len(items) - 2, -1, -1):
        items[i]["y_adj"] = min(items[i]["y_adj"], items[i + 1]["y_adj"] - min_gap)

    underflow = lower - items[0]["y_adj"]
    if underflow > 0:
        for item in items:
            item["y_adj"] += underflow

    return items

def make_compact_label(int_val, pct_val, metric_val, metric_label):
    return f"{int_val}\n{format_pct(pct_val)}\n{metric_label} {format_metric(metric_val)}"

def get_auto_label_sizes(n_slices: int):
    if n_slices <= 4:
        return {
            "inside_font": 8.3,
            "outside_font": 7.7,
            "inside_linespacing": 1.10,
            "outside_linespacing": 1.10,
            "text_scale": 1.22,
            "min_gap": 0.13
        }
    if n_slices <= 6:
        return {
            "inside_font": 7.8,
            "outside_font": 7.1,
            "inside_linespacing": 1.10,
            "outside_linespacing": 1.10,
            "text_scale": 1.24,
            "min_gap": 0.15
        }
    return {
        "inside_font": 7.2,
        "outside_font": 6.6,
        "inside_linespacing": 1.08,
        "outside_linespacing": 1.08,
        "text_scale": 1.27,
        "min_gap": 0.17
    }

def place_external_labels(ax, label_items, fontsize=7.6, linecolor="gray",
                          text_scale=1.24, min_gap=0.14, linespacing=1.10):
    left_items = [d for d in label_items if d["side"] == "left"]
    right_items = [d for d in label_items if d["side"] == "right"]

    for item in left_items + right_items:
        theta = item["theta"]
        r_text = text_scale + (0.05 if abs(np.sin(theta)) > 0.75 else 0.0)
        item["x_text"] = np.cos(theta) * r_text
        item["y"] = np.sin(theta) * r_text

    left_items = distribute_positions(left_items, min_gap=min_gap, lower=-1.28, upper=1.28)
    right_items = distribute_positions(right_items, min_gap=min_gap, lower=-1.28, upper=1.28)

    for group in [left_items, right_items]:
        for item in group:
            ha = "right" if item["side"] == "left" else "left"
            x_text = item["x_text"]
            y_text = item["y_adj"]

            ax.plot(
                [item["x_edge"], item["x_mid"]],
                [item["y_edge"], item["y_mid"]],
                color=linecolor,
                lw=0.75,
                solid_capstyle="round",
                zorder=3
            )

            ax.plot(
                [item["x_mid"], x_text],
                [item["y_mid"], y_text],
                color=linecolor,
                lw=0.75,
                solid_capstyle="round",
                zorder=3
            )

            ax.text(
                x_text,
                y_text,
                item["label"],
                ha=ha,
                va="center",
                fontsize=fontsize,
                fontweight="bold",
                color="black",
                linespacing=linespacing
            )

def draw_smart_labels_donut(ax, wedges, sizes, metric_values, total, wedgewidth, metric_label):
    external_labels = []
    auto = get_auto_label_sizes(len(wedges))

    for i, w in enumerate(wedges):
        theta1, theta2 = w.theta1, w.theta2
        angle_span = theta2 - theta1
        mid_theta = np.deg2rad((theta1 + theta2) / 2.0)

        int_val = int(sizes[i])
        pct_val = sizes[i] / total * 100.0 if total > 0 else 0
        metric_val = float(metric_values[i]) if i < len(metric_values) else 0.0

        facecolor = w.get_facecolor()
        text_color = "black" if is_light_color(facecolor) else "white"

        cx, cy = w.center
        r_outer = w.r
        r_inner = w.r - wedgewidth
        r_mid = (r_outer + r_inner) / 2.0

        label_text = make_compact_label(int_val, pct_val, metric_val, metric_label)

        if angle_span >= 48 and pct_val >= 13:
            x = cx + np.cos(mid_theta) * r_mid
            y = cy + np.sin(mid_theta) * r_mid

            ax.text(
                x, y,
                label_text,
                ha="center", va="center",
                fontsize=auto["inside_font"],
                fontweight="bold",
                color=text_color,
                linespacing=auto["inside_linespacing"]
            )
        else:
            x_edge = cx + np.cos(mid_theta) * (r_outer + 0.01)
            y_edge = cy + np.sin(mid_theta) * (r_outer + 0.01)

            x_mid = cx + np.cos(mid_theta) * (r_outer + 0.05)
            y_mid = cy + np.sin(mid_theta) * (r_outer + 0.05)

            side = "right" if np.cos(mid_theta) >= 0 else "left"

            external_labels.append({
                "label": label_text,
                "x_edge": x_edge,
                "y_edge": y_edge,
                "x_mid": x_mid,
                "y_mid": y_mid,
                "theta": mid_theta,
                "side": side
            })

    place_external_labels(
        ax,
        external_labels,
        fontsize=auto["outside_font"],
        linecolor="gray",
        text_scale=auto["text_scale"],
        min_gap=auto["min_gap"],
        linespacing=auto["outside_linespacing"]
    )

def render_pie_subbar(
    df_main,
    df_break,
    selected_phase,
    main_title,
    sub_title,
    metric_label,
    metric_total_label,
    metric_total_value
):
    sizes_main = df_main["Conteo"].values.astype(float)
    labels_main = df_main["Fase"].astype(str).values
    metric_main = df_main["xG"].values.astype(float) if "xG" in df_main.columns else np.zeros(len(df_main))

    sizes_sub = df_break["Conteo"].values.astype(float)
    labels_sub = df_break["Concepto"].astype(str).values
    metric_sub = df_break["xG"].values.astype(float) if "xG" in df_break.columns else np.zeros(len(df_break))

    wedgewidth = 0.45
    explode_target = 0.08
    dpi = 140

    try:
        target_idx = int(np.where(labels_main == str(selected_phase))[0][0])
    except Exception:
        target_idx = 0

    total_main = sizes_main.sum()
    cum_before = sizes_main[:target_idx].sum()
    center_frac = (cum_before + sizes_main[target_idx] / 2.0) / total_main if total_main > 0 else 0
    startangle = (0 - 360.0 * center_frac) % 360.0

    cmap = plt.get_cmap("tab20")
    default_sub_colors = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#ffff33"]
    sub_colors = [default_sub_colors[i % len(default_sub_colors)] for i in range(len(sizes_sub))]
    main_colors = [cmap(i % 20) for i in range(len(sizes_main))]

    fig = plt.figure(figsize=(13.6, 5.8), dpi=dpi)
    main_ax = fig.add_axes([0.05, 0.05, 0.33, 0.64])
    sub_ax = fig.add_axes([0.64, 0.05, 0.28, 0.64])

    explode = [explode_target if i == target_idx else 0 for i in range(len(labels_main))]

    wedges, _texts = main_ax.pie(
        sizes_main,
        labels=[None] * len(sizes_main),
        startangle=startangle,
        explode=explode,
        colors=main_colors,
        wedgeprops=dict(width=wedgewidth, edgecolor="w")
    )
    main_ax.set(aspect="equal")
    main_ax.set_title(main_title, fontsize=16, fontweight="bold", pad=24)

    legend_labels_main = [
        f"{labels_main[i]} | {metric_label}: {format_metric(metric_main[i])}"
        for i in range(len(labels_main))
    ]

    main_ax.legend(
        legend_labels_main,
        loc="center right",
        bbox_to_anchor=(-0.24, 0.5),
        ncol=1,
        frameon=False,
        fontsize=9.4
    )

    draw_smart_labels_donut(main_ax, wedges, sizes_main, metric_main, total_main, wedgewidth, metric_label)

    sub_ax.set_title(
        sub_title,
        fontsize=13.5,
        fontweight="bold",
        pad=28
    )

    sub_ax.text(
        0.5, 1.02,
        f"Fase: {selected_phase}",
        transform=sub_ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10.2,
        color="#555555",
        fontweight="semibold"
    )

    if len(labels_sub) > 0:
        y_pos = np.arange(len(labels_sub))
        bars = sub_ax.barh(
            y_pos,
            sizes_sub,
            color=sub_colors,
            edgecolor="none",
            height=0.50
        )

        sub_ax.set_yticks(y_pos)
        sub_ax.set_yticklabels(labels_sub, fontsize=9.1)
        sub_ax.invert_yaxis()

        max_width = max(sizes_sub) if len(sizes_sub) > 0 else 0
        inner_x = max(max_width * 0.03, 0.08)
        outer_offset = max(max_width * 0.03, 0.12)

        for i, bar in enumerate(bars):
            width = bar.get_width()
            metric_val = metric_sub[i]
            bar_color = bar.get_facecolor()
            inside_color = text_color_for_bar(bar_color)

            x_inside = min(inner_x, width * 0.5) if width > 0 else inner_x

            sub_ax.text(
                x_inside,
                bar.get_y() + bar.get_height() / 2,
                f"{int(width)}",
                va="center",
                ha="left" if width > inner_x * 1.8 else "center",
                fontsize=8.5,
                fontweight="bold",
                color=inside_color
            )

            sub_ax.text(
                width + outer_offset,
                bar.get_y() + bar.get_height() / 2,
                f"{metric_label} {format_metric(metric_val)}",
                va="center",
                ha="left",
                fontsize=8.5,
                fontweight="bold",
                color="black"
            )

        sub_ax.grid(axis="x", alpha=0.14)
        sub_ax.set_axisbelow(True)
        sub_ax.spines["top"].set_visible(False)
        sub_ax.spines["right"].set_visible(False)
        sub_ax.spines["left"].set_visible(False)
        sub_ax.spines["bottom"].set_alpha(0.2)

        sub_ax.tick_params(axis="x", labelsize=8.2)
        sub_ax.tick_params(axis="y", length=0)

        sub_ax.set_xlim(0, max_width * 1.42 if max_width > 0 else 1)

    if len(wedges) > 0:
        target_wedge = wedges[target_idx]
        theta1, theta2 = target_wedge.theta1, target_wedge.theta2
        mid_theta = np.deg2rad((theta1 + theta2) / 2.0)
        r_outer = target_wedge.r

        start_data = (
            target_wedge.center[0] + np.cos(mid_theta) * (r_outer + 0.35),
            target_wedge.center[1] + np.sin(mid_theta) * (r_outer + 0.35)
        )

        start_fig = fig.transFigure.inverted().transform(
            main_ax.transData.transform(start_data)
        )

        sub_pos = sub_ax.get_position()
        end_fig = (
            sub_pos.x0 - 0.16,
            sub_pos.y0 + sub_pos.height * 0.52
        )

        arrow = ConnectionPatch(
            xyA=start_fig, coordsA=fig.transFigure,
            xyB=end_fig, coordsB=fig.transFigure,
            arrowstyle="->",
            linewidth=1.0,
            color="gray",
            mutation_scale=10,
            connectionstyle="arc3,rad=0.05",
            zorder=6
        )
        arrow.set_clip_on(False)
        fig.add_artist(arrow)

    # xG/xGC acumulado sutil en esquina superior derecha
    fig.text(
        0.975,
        0.955,
        f"{metric_total_label}: {format_metric(metric_total_value)}",
        ha="right",
        va="top",
        fontsize=9.2,
        color="#666666"
    )

    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    return fig

def get_logo_path(team_name: str, logo_dir: str = "."):
    if not team_name:
        return None

    candidates = [
        team_name.strip(),
        team_name.strip().replace("/", "-"),
        team_name.strip().replace("\\", "-"),
        team_name.strip().replace(" ", "_"),
    ]

    exts = [".png", ".jpg", ".jpeg", ".webp"]

    for base in candidates:
        for ext in exts:
            path = os.path.join(logo_dir, f"{base}{ext}")
            if os.path.exists(path):
                return path
    return None

def show_team_logo(team_name: str, width: int = 150):
    logo_path = get_logo_path(team_name, LOGO_DIR)
    if logo_path:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.image(logo_path, width=width)

def show_sidebar_logo(team_name: str, width: int = 70):
    logo_path = get_logo_path(team_name, LOGO_DIR)
    if logo_path:
        st.sidebar.image(logo_path, width=width)

# ---------- Título principal ----------
st.title("Remates por Fase")

# ---------- Lectura automática ----------
df = None

with st.spinner("Cargando datos..."):
    try:
        df = load_via_csv_export(SHEET_URL)
    except Exception:
        pass

if df is None:
    cred_path = os.path.join(os.getcwd(), "credenciales.json")
    if os.path.exists(cred_path) and HAS_GSPREAD:
        try:
            client = client_from_service_account_file(cred_path)
            ws = open_worksheet_by_url(client, SHEET_URL)
            df = pd.DataFrame(ws.get_all_records())
        except Exception:
            pass

if df is None and HAS_GSPREAD:
    try:
        if "gdrive_service_account" in st.secrets:
            sa_info = dict(st.secrets["gdrive_service_account"])
            client = client_from_service_account_info(sa_info)
            ws = open_worksheet_by_url(client, SHEET_URL)
            df = pd.DataFrame(ws.get_all_records())
    except Exception:
        pass

if df is None:
    st.error("No fue posible leer la hoja automáticamente.")
    st.stop()

df_original = df.copy()
cols = [c for c in df.columns]

main_col = find_column_exact_or_similar(cols, "Fase")
sub_col = find_column_exact_or_similar(cols, "Concepto")
team_col = find_column_exact_or_similar(cols, "Equipo")
jornada_col = find_column_exact_or_similar(cols, "Jornada")
xg_col = find_column_exact_or_similar(cols, "Valor xG")

if main_col is None or sub_col is None or team_col is None or jornada_col is None or xg_col is None:
    st.error("No se encontraron las columnas requeridas en la hoja, incluyendo 'Valor xG'.")
    st.stop()

# ---------- Limpieza base ----------
df = df.copy()
for c in [main_col, sub_col, team_col, jornada_col]:
    df[c] = df[c].fillna("Sin dato").astype(str).str.strip()

df[xg_col] = (
    df[xg_col]
    .astype(str)
    .str.replace(",", ".", regex=False)
    .str.strip()
)
df[xg_col] = pd.to_numeric(df[xg_col], errors="coerce").fillna(0.0)

for c in [main_col, sub_col, team_col, jornada_col]:
    df_original[c] = df_original[c].fillna("Sin dato").astype(str).str.strip()

if MAIN_TEAM_NAME not in df[team_col].unique().tolist():
    st.error(f"No se encontró el equipo principal '{MAIN_TEAM_NAME}' en la columna Equipo.")
    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
show_sidebar_logo(MAIN_TEAM_NAME, width=180)
st.sidebar.header("Filtros")

main_team_df = df[df[team_col] == MAIN_TEAM_NAME].copy()

all_main_jornadas = sort_mixed_values(
    main_team_df[jornada_col].dropna().astype(str).str.strip().unique().tolist()
)

if not all_main_jornadas:
    st.warning(f"No hay jornadas disponibles para {MAIN_TEAM_NAME}.")
    st.stop()

latest_jornada = sorted(all_main_jornadas, key=jornada_key)[-1]

with st.sidebar.expander("Jornada(s)", expanded=False):
    select_all_jornadas = st.checkbox(
        "Todas",
        value=False,
        key="check_all_jornadas"
    )

    if select_all_jornadas:
        selected_main_jornadas = all_main_jornadas
    else:
        selected_main_jornadas = st.multiselect(
            "Selecciona una o varias jornadas",
            options=all_main_jornadas,
            default=[latest_jornada],
            label_visibility="collapsed",
            key="selected_main_jornadas_multi"
        )

if not selected_main_jornadas:
    st.warning("Selecciona al menos una jornada.")
    st.stop()

df_selected_jornadas = df[df[jornada_col].isin(selected_main_jornadas)].copy()

auto_rival_teams = (
    df_selected_jornadas.loc[df_selected_jornadas[team_col] != MAIN_TEAM_NAME, team_col]
    .dropna()
    .astype(str)
    .str.strip()
    .unique()
    .tolist()
)
auto_rival_teams = sorted(auto_rival_teams, key=lambda x: x.lower())

available_views = [MAIN_TEAM_NAME]
if auto_rival_teams:
    available_views.append("Rival")

selected_view = st.sidebar.radio(
    "Ver equipo",
    options=available_views,
    index=0
)

metric_label = get_metric_label(selected_view)
metric_total_label = get_metric_total_label(selected_view)

if selected_view == MAIN_TEAM_NAME:
    selected_team_label = MAIN_TEAM_NAME
    df_selected_team = df[
        (df[team_col] == MAIN_TEAM_NAME) &
        (df[jornada_col].isin(selected_main_jornadas))
    ].copy()

    df_table_general = df_original[
        (df_original[team_col] == MAIN_TEAM_NAME) &
        (df_original[jornada_col].isin(selected_main_jornadas))
    ].copy()
else:
    if not auto_rival_teams:
        st.warning("No se pudieron determinar rivales para la(s) jornada(s) seleccionada(s).")
        st.stop()

    selected_team_label = "Rivales acumulados"
    df_selected_team = df[
        (df[team_col] != MAIN_TEAM_NAME) &
        (df[jornada_col].isin(selected_main_jornadas))
    ].copy()

    df_table_general = df_original[
        (df_original[team_col] != MAIN_TEAM_NAME) &
        (df_original[jornada_col].isin(selected_main_jornadas))
    ].copy()

metric_total_value = df_selected_team[xg_col].sum() if not df_selected_team.empty else 0.0

df_phase = build_phase_table(df_selected_team, main_col, xg_col)
fase_options = df_phase["Fase"].astype(str).tolist()

if not fase_options:
    st.warning(f"No hay fases disponibles para {selected_team_label} en la(s) jornada(s) seleccionada(s).")
    st.stop()

current_selected_subpie = st.session_state.get("selected_subpie_single")
if current_selected_subpie not in fase_options:
    current_selected_subpie = fase_options[0]

selected_subpie_fase = st.sidebar.selectbox(
    "Fase a visualizar en el subpie",
    options=fase_options,
    index=fase_options.index(current_selected_subpie),
    key="selected_subpie_single"
)

# =========================================================
# TABLAS FINALES
# =========================================================
_, df_break = build_break_table(
    df_selected_team, main_col, sub_col, xg_col, selected_subpie_fase
)

df_table_phase = df_table_general[
    df_table_general[main_col] == selected_subpie_fase
].copy()

# =========================================================
# RENDER
# =========================================================
fig = render_pie_subbar(
    df_main=df_phase,
    df_break=df_break,
    selected_phase=selected_subpie_fase,
    main_title=f"Remates por Fase - {selected_team_label}",
    sub_title="Desglose - Finalización",
    metric_label=metric_label,
    metric_total_label=metric_total_label,
    metric_total_value=metric_total_value
)

if selected_view == MAIN_TEAM_NAME:
    show_team_logo(MAIN_TEAM_NAME, width=150)

st.pyplot(fig, use_container_width=True)

# =========================================================
# TABLAS ORIGINALES FILTRADAS - ALINEADAS DEBAJO
# =========================================================
st.markdown("### Datos originales filtrados")

left_table_col, right_table_col = st.columns([1, 1], gap="large")

with left_table_col:
    st.markdown(f"**Tabla Principal (gráfico pie) - {selected_team_label}**")
    st.dataframe(
        df_table_general,
        use_container_width=True,
        hide_index=True,
        height=320
    )

with right_table_col:
    st.markdown(f"**Tabla filtrada (Subpie) - Fase: {selected_subpie_fase}**")
    st.dataframe(
        df_table_phase,
        use_container_width=True,
        hide_index=True,
        height=320
    )
