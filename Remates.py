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

def build_phase_table(df_filtered, main_col):
    if df_filtered.empty:
        return pd.DataFrame(columns=["Fase", "Conteo"])
    return (
        df_filtered
        .groupby(main_col, dropna=False)
        .size()
        .reset_index(name="Conteo")
        .rename(columns={main_col: "Fase"})
        .sort_values("Conteo", ascending=False)
        .reset_index(drop=True)
    )

def build_break_table(df_filtered, main_col, sub_col, selected_phase):
    rows_target = df_filtered[df_filtered[main_col] == selected_phase].copy()
    df_break = (
        rows_target
        .groupby(sub_col, dropna=False)
        .size()
        .reset_index(name="Conteo")
        .rename(columns={sub_col: "Concepto"})
        .sort_values("Conteo", ascending=False)
        .reset_index(drop=True)
    )
    if df_break.empty:
        df_break = pd.DataFrame({"Concepto": ["Sin detalle"], "Conteo": [len(rows_target)]})
    return rows_target, df_break

def render_pie_subpie(df_main, df_break, selected_phase, main_title, sub_title):
    sizes_main = df_main["Conteo"].values.astype(float)
    labels_main = df_main["Fase"].astype(str).values
    sizes_sub = df_break["Conteo"].values.astype(float)
    labels_sub = df_break["Concepto"].astype(str).values

    wedgewidth = 0.45
    explode_target = 0.08
    sub_size = 0.50
    sub_left = 0.40
    sub_bottom = 0.35
    dpi = 140
    stop_fraction = 0.45

    try:
        target_idx = int(np.where(labels_main == str(selected_phase))[0][0])
    except Exception:
        target_idx = 0

    total = sizes_main.sum()
    cum_before = sizes_main[:target_idx].sum()
    center_frac = (cum_before + sizes_main[target_idx] / 2.0) / total if total > 0 else 0
    startangle = (0 - 360.0 * center_frac) % 360.0

    cmap = plt.get_cmap("tab20")
    default_sub_colors = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33']
    sub_colors = [default_sub_colors[i % len(default_sub_colors)] for i in range(len(sizes_sub))]
    main_colors = [cmap(i % 20) for i in range(len(sizes_main))]

    fig = plt.figure(figsize=(14, 6), dpi=dpi)
    main_ax = fig.add_axes([0.06, 0.15, 0.44, 0.7])

    explode = [explode_target if i == target_idx else 0 for i in range(len(labels_main))]

    wedges, _texts = main_ax.pie(
        sizes_main,
        labels=[None] * len(sizes_main),
        startangle=startangle,
        explode=explode,
        colors=main_colors,
        wedgeprops=dict(width=wedgewidth, edgecolor='w')
    )
    main_ax.set(aspect="equal")
    main_ax.set_title(main_title, fontsize=16, fontweight='bold')
    main_ax.legend(
        list(labels_main),
        loc='center right',
        bbox_to_anchor=(-0.12, 0.5),
        ncol=1,
        frameon=False,
        fontsize=11
    )

    for i, w in enumerate(wedges):
        theta1, theta2 = w.theta1, w.theta2
        mid_theta = np.deg2rad((theta1 + theta2) / 2.0)
        text_radius = w.r - (wedgewidth / 2.0)
        cx, cy = w.center
        x = cx + np.cos(mid_theta) * text_radius
        y = cy + np.sin(mid_theta) * text_radius
        dy = 0.06
        int_val = int(sizes_main[i])
        pct_val = sizes_main[i] / total * 100.0 if total > 0 else 0

        main_ax.text(
            x, y + dy, f"{int_val}",
            ha='center', va='bottom',
            fontsize=12, fontweight='bold', color='white'
        )
        main_ax.text(
            x, y - dy, f"{pct_val:.0f}%",
            ha='center', va='top',
            fontsize=10, fontweight='bold', color='white'
        )

    sub_ax = fig.add_axes([sub_left, sub_bottom, sub_size, sub_size])

    def subtxt(pct, allvals):
        absolute = int(round(pct / 100.0 * np.sum(allvals)))
        return f"{absolute}\n{pct:.0f}%"

    _, _, sub_autotexts = sub_ax.pie(
        sizes_sub,
        labels=[None] * len(sizes_sub),
        colors=sub_colors,
        startangle=startangle,
        autopct=lambda pct: subtxt(pct, sizes_sub),
        pctdistance=0.65,
        textprops=dict(fontsize=10),
        wedgeprops=dict(edgecolor='w')
    )
    sub_ax.set(aspect="equal")
    sub_ax.set_title(sub_title, fontsize=14, fontweight='bold', loc='center')
    sub_ax.legend(
        list(labels_sub),
        loc='center left',
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        fontsize=10
    )

    for t in sub_autotexts:
        t.set_fontsize(10)
        t.set_fontweight('bold')
        t.set_color('white')

    if len(wedges) > 0:
        target_wedge = wedges[target_idx]
        theta1, theta2 = target_wedge.theta1, target_wedge.theta2
        mid_theta = np.deg2rad((theta1 + theta2) / 2.0)
        r_outer = target_wedge.r
        start_point = (
            target_wedge.center[0] + np.cos(mid_theta) * (r_outer + 0.01),
            target_wedge.center[1] + np.sin(mid_theta) * (r_outer + 0.01)
        )

        main_center_fig = fig.transFigure.inverted().transform(
            main_ax.transData.transform(target_wedge.center)
        )
        sub_center_fig = np.array([sub_left + sub_size / 2.0, sub_bottom + sub_size / 2.0])
        end_fig = main_center_fig + stop_fraction * (sub_center_fig - main_center_fig)
        disp_coords = fig.transFigure.transform(end_fig)
        end_data = sub_ax.transData.inverted().transform(disp_coords)

        arrow = ConnectionPatch(
            xyA=start_point, coordsA="data", axesA=main_ax,
            xyB=tuple(end_data), coordsB="data", axesB=sub_ax,
            arrowstyle="->", linewidth=1.6, color="gray", zorder=6
        )
        arrow.set_clip_on(False)
        fig.add_artist(arrow)

    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    return fig

def get_rivals_from_selected_jornada(df_base, team_col, jornada_col, selected_jornada, main_team_name):
    if not selected_jornada:
        return []
    tmp = df_base[df_base[jornada_col] == selected_jornada].copy()
    rivals = (
        tmp.loc[tmp[team_col] != main_team_name, team_col]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )
    return sorted(rivals, key=lambda x: x.lower())

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

cols = [c for c in df.columns]

main_col = find_column_exact_or_similar(cols, "Fase")
sub_col = find_column_exact_or_similar(cols, "Concepto")
team_col = find_column_exact_or_similar(cols, "Equipo")
jornada_col = find_column_exact_or_similar(cols, "Jornada")

if main_col is None or sub_col is None or team_col is None or jornada_col is None:
    st.error("No se encontraron las columnas requeridas en la hoja.")
    st.stop()

# ---------- Limpieza base ----------
df = df.copy()
for c in [main_col, sub_col, team_col, jornada_col]:
    df[c] = df[c].fillna("Sin dato").astype(str).str.strip()

if MAIN_TEAM_NAME not in df[team_col].unique().tolist():
    st.error(f"No se encontró el equipo principal '{MAIN_TEAM_NAME}' en la columna Equipo.")
    st.stop()

# =========================================================
# SIDEBAR
# =========================================================
show_sidebar_logo(MAIN_TEAM_NAME, width=180)
st.sidebar.header(f"Filtros - {MAIN_TEAM_NAME}")

main_team_df = df[df[team_col] == MAIN_TEAM_NAME].copy()

all_main_jornadas = sort_mixed_values(
    main_team_df[jornada_col].dropna().astype(str).str.strip().unique().tolist()
)

if not all_main_jornadas:
    st.warning(f"No hay jornadas disponibles para {MAIN_TEAM_NAME}.")
    st.stop()

current_single_main_jornada = st.session_state.get("selected_main_jornada_single")
if current_single_main_jornada not in all_main_jornadas:
    current_single_main_jornada = all_main_jornadas[0]

selected_main_jornada = st.sidebar.selectbox(
    "Jornada",
    options=all_main_jornadas,
    index=all_main_jornadas.index(current_single_main_jornada),
    key="selected_main_jornada_single"
)

df_main_filtered = main_team_df[main_team_df[jornada_col] == selected_main_jornada].copy()
df_main_phase = build_phase_table(df_main_filtered, main_col)
main_fase_options = df_main_phase["Fase"].astype(str).tolist()

if not main_fase_options:
    st.warning(f"No hay fases disponibles para {MAIN_TEAM_NAME} en la jornada seleccionada.")
    st.stop()

current_single_main_subpie = st.session_state.get("selected_main_subpie_single")
if current_single_main_subpie not in main_fase_options:
    current_single_main_subpie = main_fase_options[0]

selected_main_subpie_fase = st.sidebar.selectbox(
    "Fase a visualizar en el subpie",
    options=main_fase_options,
    index=main_fase_options.index(current_single_main_subpie),
    key="selected_main_subpie_single"
)

st.sidebar.markdown("---")
st.sidebar.header("Filtros - Rival")

auto_rival_teams = get_rivals_from_selected_jornada(
    df_base=df,
    team_col=team_col,
    jornada_col=jornada_col,
    selected_jornada=selected_main_jornada,
    main_team_name=MAIN_TEAM_NAME
)

if not auto_rival_teams:
    st.warning("No se pudo determinar automáticamente el rival para la jornada seleccionada.")
    st.stop()

selected_rival_team = auto_rival_teams[0]

st.sidebar.text_input(
    "Equipo rival (automático)",
    value=selected_rival_team,
    disabled=True,
    key="auto_rival_display"
)

show_sidebar_logo(selected_rival_team, width=70)

# El rival usa automáticamente la misma jornada seleccionada en Tigres
st.sidebar.text_input(
    "Jornada rival (automática)",
    value=selected_main_jornada,
    disabled=True,
    key="auto_rival_jornada_display"
)

df_rival_base = df[df[team_col] == selected_rival_team].copy()
df_rival_filtered = df_rival_base[df_rival_base[jornada_col] == selected_main_jornada].copy()

df_rival_phase = build_phase_table(df_rival_filtered, main_col)
rival_fase_options = df_rival_phase["Fase"].astype(str).tolist()

if not rival_fase_options:
    st.warning("No hay fases disponibles para el rival en la misma jornada seleccionada.")
    st.stop()

current_single_rival_subpie = st.session_state.get("selected_rival_subpie_single")
if current_single_rival_subpie not in rival_fase_options:
    current_single_rival_subpie = rival_fase_options[0]

selected_rival_subpie_fase = st.sidebar.selectbox(
    "Fase a visualizar en el subpie rival",
    options=rival_fase_options,
    index=rival_fase_options.index(current_single_rival_subpie),
    key="selected_rival_subpie_single"
)

# =========================================================
# TABLAS FINALES
# =========================================================
_, df_main_break = build_break_table(df_main_filtered, main_col, sub_col, selected_main_subpie_fase)
_, df_rival_break = build_break_table(df_rival_filtered, main_col, sub_col, selected_rival_subpie_fase)

# =========================================================
# RENDER
# =========================================================
fig_main = render_pie_subpie(
    df_main=df_main_phase,
    df_break=df_main_break,
    selected_phase=selected_main_subpie_fase,
    main_title=f"Remates por Fase - {MAIN_TEAM_NAME}",
    sub_title="Desglose - Finalización"
)

show_team_logo(MAIN_TEAM_NAME, width=150)
st.pyplot(fig_main)

st.markdown("<hr style='margin: 28px 0; opacity: 0.22;'>", unsafe_allow_html=True)

fig_rival = render_pie_subpie(
    df_main=df_rival_phase,
    df_break=df_rival_break,
    selected_phase=selected_rival_subpie_fase,
    main_title=f"Remates por Fase - {selected_rival_team}",
    sub_title="Desglose - Finalización"
)

show_team_logo(selected_rival_team, width=150)
st.pyplot(fig_rival)