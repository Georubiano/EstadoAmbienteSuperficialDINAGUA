"""
Balance hídrico por cuenca nivel 2 — app de Streamlit.

Muestra, por cada cuenca nivel 2 de Uruguay, el volumen total concedido
(solicitudes de aprovechamiento hídrico) y la cantidad de obras por tipo
(represas, tajamares, tanques, reservorios).

Datos de entrada (carpeta data/):
  - solicitudes_limpio.csv : una fila por solicitud/obra, ya unificada
    a partir de las 6 planillas originales (una por cuenca nivel 1).
  - cuencas_n2.geojson     : polígonos de las 48 cuencas nivel 2
    (capa "c098"), con la propiedad `codcuenca` para el join.

Ejecutar localmente:
    streamlit run streamlit_app.py
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import pydeck as pdk
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"

# App 100% modo oscuro: template de Plotly + tema de Streamlit (.streamlit/config.toml)
pio.templates.default = "plotly_dark"

# Orden fijo de tipos de obra
TIPOS_ORDER = [
    "Represa Grande", "Represa Mediana", "Represa Chica",
    "Tajamar Grande", "Tajamar Mediano", "Tajamar Chico",
    "Tanque Excavado", "Reservorio/Otros",
]

# Paleta categórica (cuenca nivel 1)
N1_COLORS = {
    "Río Uruguay": "#3987e5",
    "Río de la Plata": "#d95926",
    "Océano Atlántico": "#199e70",
    "Laguna Merín": "#c98500",
    "Río Negro": "#d55181",
    "Santa Lucía": "#2fa72f",
}

# Rampa secuencial para el mapa coroplético
SEQ_SCALE = [
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b",
]

# Paleta categórica de 8 colores para tipos de obra
TIPO_COLORS = {
    "Represa Grande": "#3987e5",
    "Represa Mediana": "#d95926",
    "Represa Chica": "#199e70",
    "Tajamar Grande": "#c98500",
    "Tajamar Mediano": "#d55181",
    "Tajamar Chico": "#008300",
    "Tanque Excavado": "#9085e9",
    "Reservorio/Otros": "#e66767",
}


def hex_a_rgba(hex_color, alpha=200):
    h = hex_color.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha]


TIPO_COLORS_RGBA = {k: hex_a_rgba(v) for k, v in TIPO_COLORS.items()}

MAPA_ESTILO = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"


def miles(n):
    return f"{n:,.0f}".replace(",", ".")


st.set_page_config(
    page_title="Balance hídrico por cuenca",
    page_icon="💧",
    layout="wide",
)


# --------------------------------------------------------------------------
# Carga de datos
# --------------------------------------------------------------------------
@st.cache_data
def load_data():
    df = pd.read_csv(DATA_DIR / "solicitudes_limpio.csv")
    df["codcuenca"] = df["codcuenca"].astype(int)

    with open(DATA_DIR / "cuencas_n2.geojson", encoding="utf-8") as f:
        geojson = json.load(f)

    props = pd.DataFrame([feat["properties"] for feat in geojson["features"]])
    props["codcuenca"] = props["codcuenca"].astype(int)
    props = props.rename(columns={"nombre_cue": "nombre_cuenca", "area": "area_km2"})
    props = props[["codcuenca", "nombre_cuenca", "area_km2", "cabecera"]]

    return df, geojson, props


df, geojson, cuencas_meta = load_data()

nombre_por_codigo = dict(zip(cuencas_meta["codcuenca"], cuencas_meta["nombre_cuenca"]))
n1_por_codigo = df.groupby("codcuenca")["cuenca_n1"].agg(lambda s: s.mode().iat[0]).to_dict()
codigos_sin_poligono = sorted(set(df["codcuenca"]) - set(cuencas_meta["codcuenca"]))


# --------------------------------------------------------------------------
# Sidebar — filtros
# --------------------------------------------------------------------------
st.sidebar.header("Filtros")

n1_options = sorted(df["cuenca_n1"].dropna().unique())
n1_selected = st.sidebar.multiselect(
    "Cuenca nivel 1", n1_options, default=n1_options,
)

search = st.sidebar.text_input("Buscar cuenca nivel 2 (nombre o código)")

st.sidebar.markdown("---")
st.sidebar.caption(
    "Fuente: 6 planillas de solicitudes de aprovechamiento hídrico "
    "y shapefile de cuencas nivel 2 (capa c098)."
)
if codigos_sin_poligono:
    st.sidebar.caption(f"Nota: la cuenca {codigos_sin_poligono} no tiene polígono en el shapefile.")

dff = df[df["cuenca_n1"].isin(n1_selected)].copy()
if search:
    s = search.strip().lower()
    mask = (
        dff["codcuenca"].astype(str).str.contains(s)
        | dff["codcuenca"].map(nombre_por_codigo).fillna("").str.lower().str.contains(s)
    )
    dff = dff[mask]

if dff.empty:
    st.warning("No hay datos para los filtros seleccionados.")
    st.stop()


# --------------------------------------------------------------------------
# Agregaciones
# --------------------------------------------------------------------------
# Detectar dinámicamente el nombre de la columna de embalse si existe
col_embalse = next((c for c in dff.columns if "embalse" in c.lower()), None)

agg_dict = {
    "volumen": ("volumen", "sum"),
    "n_obras": ("volumen", "count"),
}
if col_embalse:
    agg_dict["Volúmen de Embalse"] = (col_embalse, "sum")
else:
    agg_dict["Volúmen de Embalse"] = ("volumen", "sum")

por_cuenca = (
    dff.groupby("codcuenca")
    .agg(**agg_dict)
    .reset_index()
)
por_cuenca["nombre_cuenca"] = por_cuenca["codcuenca"].map(nombre_por_codigo)
por_cuenca["cuenca_n1"] = por_cuenca["codcuenca"].map(n1_por_codigo)
por_cuenca["area_km2"] = por_cuenca["codcuenca"].map(
    dict(zip(cuencas_meta["codcuenca"], cuencas_meta["area_km2"]))
)
por_cuenca = por_cuenca.sort_values("volumen", ascending=False)

tipo_por_cuenca = (
    dff.pivot_table(
        index="codcuenca", columns="tipo_obra_agr", values="volumen", aggfunc="count", fill_value=0
    )
    .reindex(columns=TIPOS_ORDER, fill_value=0)
)


# --------------------------------------------------------------------------
# Encabezado + KPIs
# --------------------------------------------------------------------------
st.title("💧 Derechos de uso otorgados clasificados por volúmenes y obras en cuencas nivel 2")
st.caption(
    f"{por_cuenca.shape[0]} cuencas nivel 2 · {len(n1_selected)} de 6 cuencas nivel 1 · "
    f"{len(dff):,} solicitudes".replace(",", ".")
)

c1, c2, c3 = st.columns(3)
c1.metric("Volumen total", f"{dff['volumen'].sum() / 1e6:,.1f} hm³".replace(",", "."))
c2.metric("Obras registradas", f"{len(dff):,}".replace(",", "."))
c3.metric("Cuencas nivel 2", f"{por_cuenca.shape[0]}")

st.markdown("---")

# --------------------------------------------------------------------------
# Mapa Coroplético (GeoJSON Nivel 2)
# --------------------------------------------------------------------------
st.subheader("Volumen otorgado por cuenca")

map_df = por_cuenca[por_cuenca["codcuenca"].isin(
    [f["properties"]["codcuenca"] for f in geojson["features"]]
)]

# Leyenda visual para el mapa coroplético de volúmenes (rampa de azules)
st.markdown(
    """
    <div style='display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:12px;color:#ccc;'>
        <span><b>Menor volumen</b></span>
        <div style='display:flex;height:12px;width:150px;border-radius:4px;overflow:hidden;'>
            <div style='background:#cde2fb;flex:1;'></div>
            <div style='background:#9ec5f4;flex:1;'></div>
            <div style='background:#6da7ec;flex:1;'></div>
            <div style='background:#3987e5;flex:1;'></div>
            <div style='background:#256abf;flex:1;'></div>
            <div style='background:#184f95;flex:1;'></div>
            <div style='background:#0d366b;flex:1;'></div>
        </div>
        <span><b>Mayor volumen</b></span>
    </div>
    """,
    unsafe_allow_html=True,
)

fig_map = px.choropleth(
    map_df,
    geojson=geojson,
    locations="codcuenca",
    featureidkey="properties.codcuenca",
    color="volumen",
    color_continuous_scale=SEQ_SCALE,
    hover_name="nombre_cuenca",
    hover_data={"codcuenca": True, "volumen": ":,.0f", "n_obras": True},
)
fig_map.update_geos(fitbounds="locations", visible=False)
fig_map.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
    coloraxis_showscale=False,  # Ocultamos la barra vertical por defecto para usar la leyenda horizontal limpia
    height=700,
)
st.plotly_chart(fig_map, use_container_width=True)

st.markdown("---")

# --------------------------------------------------------------------------
# Distribución geográfica de los derechos de uso (puntos)
# --------------------------------------------------------------------------
st.header("🗺️ Distribución geográfica de los derechos de uso")

df_mapa = dff[["lat", "lon", "uso", "volumen", "tipo_obra_agr"]].copy()
df_mapa["lat"] = pd.to_numeric(df_mapa["lat"], errors="coerce")
df_mapa["lon"] = pd.to_numeric(df_mapa["lon"], errors="coerce")
df_mapa = df_mapa[
    df_mapa["lat"].between(-35.5, -30.0) & df_mapa["lon"].between(-59.5, -53.0)
    ].dropna(subset=["lat", "lon"])

if df_mapa.empty:
    st.warning("No hay puntos georreferenciados para los filtros seleccionados.")
else:
    modo_mapa = st.radio(
        "Mapa",
        ["Tipo de uso", "Tipo de obra", "Volumen"],
        horizontal=True,
    )

    if modo_mapa == "Tipo de uso":
        usos_unicos = sorted(df_mapa["uso"].dropna().unique())
        tab10 = plt.colormaps["tab10"].resampled(max(len(usos_unicos), 1))
        color_map = {}
        leyenda_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;'>"
        for i, uso in enumerate(usos_unicos):
            r, g, b, _ = tab10(i)
            color_map[uso] = [int(r * 255), int(g * 255), int(b * 255), 200]
            hex_c = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
            leyenda_html += (
                f"<span style='background:{hex_c};color:white;"
                f"padding:3px 10px;border-radius:12px;font-size:12px;'>{uso}</span>"
            )
        leyenda_html += "</div>"

        df_mapa["color"] = df_mapa["uso"].apply(lambda u: color_map.get(u, [150, 150, 150, 180]))

        st.markdown(leyenda_html, unsafe_allow_html=True)
        st.caption(f"📍 {miles(len(df_mapa))} registros georreferenciados")

        layer = pdk.Layer(
            "ScatterplotLayer", data=df_mapa,
            get_position=["lon", "lat"], get_color="color",
            get_radius=3000, pickable=True, auto_highlight=True,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(latitude=-32.5, longitude=-56.0, zoom=6),
                map_style=MAPA_ESTILO,
                tooltip={"text": "Uso: {uso}"},
            ),
            height=600,
        )

    elif modo_mapa == "Tipo de obra":
        df_mapa["color_tipo"] = df_mapa["tipo_obra_agr"].apply(
            lambda t: TIPO_COLORS_RGBA.get(t, [150, 150, 150, 180])
        )
        tipos_presentes = [t for t in TIPOS_ORDER if t in df_mapa["tipo_obra_agr"].unique()]

        leyenda_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;'>"
        for tipo in tipos_presentes:
            leyenda_html += (
                f"<span style='background:{TIPO_COLORS[tipo]};color:white;"
                f"padding:3px 10px;border-radius:12px;font-size:12px;'>{tipo}</span>"
            )
        leyenda_html += "</div>"

        st.markdown(leyenda_html, unsafe_allow_html=True)
        st.caption(f"📍 {miles(len(df_mapa))} registros georreferenciados")

        layer = pdk.Layer(
            "ScatterplotLayer", data=df_mapa,
            get_position=["lon", "lat"], get_color="color_tipo",
            get_radius=3000, pickable=True, auto_highlight=True,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(latitude=-32.5, longitude=-56.0, zoom=6),
                map_style=MAPA_ESTILO,
                tooltip={"text": "Tipo de obra: {tipo_obra_agr}"},
            ),
            height=600,
        )

    else:
        df_mapa_vol = df_mapa.dropna(subset=["volumen"]).copy()
        vol_p95 = df_mapa_vol["volumen"].quantile(0.95) or 1
        df_mapa_vol["vol_norm"] = (df_mapa_vol["volumen"].clip(upper=vol_p95) / vol_p95).fillna(0)
        cmap_vol = plt.colormaps["coolwarm"]
        df_mapa_vol["color"] = df_mapa_vol["vol_norm"].apply(
            lambda n: [int(c * 255) for c in cmap_vol(n)[:3]] + [200]
        )
        df_mapa_vol["radio"] = (1500 + df_mapa_vol["vol_norm"] * 6500).astype(int)

        vol_min = int(df_mapa_vol["volumen"].min())
        vol_med = int(df_mapa_vol["volumen"].median())
        vol_max = int(vol_p95)
        r_b, g_b, b_b, _ = cmap_vol(0.0)
        r_m, g_m, b_m, _ = cmap_vol(0.5)
        r_a, g_a, b_a, _ = cmap_vol(1.0)
        hex_b = "#{:02x}{:02x}{:02x}".format(int(r_b * 255), int(g_b * 255), int(b_b * 255))
        hex_m = "#{:02x}{:02x}{:02x}".format(int(r_m * 255), int(g_m * 255), int(b_m * 255))
        hex_a = "#{:02x}{:02x}{:02x}".format(int(r_a * 255), int(g_a * 255), int(b_a * 255))

        st.markdown(
            f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:8px;"
            f"margin-bottom:12px;font-size:12px;'>"
            f"<span>Volumen:</span>"
            f"<span style='background:{hex_b};color:white;padding:3px 10px;"
            f"border-radius:12px;'>Bajo (&lt;{miles(vol_min)} m³)</span>"
            f"<span style='background:{hex_m};color:white;padding:3px 10px;"
            f"border-radius:12px;'>Medio (~{miles(vol_med)} m³)</span>"
            f"<span style='background:{hex_a};color:white;padding:3px 10px;"
            f"border-radius:12px;'>Alto (&gt;{miles(vol_max)} m³)</span>"
            f"<span style='color:#aaa;'>Tamaño proporcional</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"📍 {miles(len(df_mapa_vol))} registros con volumen georreferenciados")

        layer = pdk.Layer(
            "ScatterplotLayer", data=df_mapa_vol,
            get_position=["lon", "lat"], get_color="color",
            get_radius="radio", pickable=True, auto_highlight=True,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(latitude=-32.5, longitude=-56.0, zoom=6),
                map_style=MAPA_ESTILO,
                tooltip={"text": "Volumen: {volumen} m³\nUso: {uso}"},
            ),
            height=600,
        )
# --------------------------------------------------------------------------
# Detalle por cuenca — cantidad de obras por tipo y uso
# --------------------------------------------------------------------------
st.subheader("Cantidad de obras")
opciones = ["— Total de la selección —"] + [
    f"{row.nombre_cuenca} (#{row.codcuenca})" for row in por_cuenca.itertuples()
]
elegido = st.selectbox("Elegí una cuenca nivel 2 (o dejá el total agregado)", opciones)

if elegido == opciones[0]:
    dff_sel = dff
    titulo = "Total de la selección actual"
else:
    cod = int(elegido.split("#")[-1].rstrip(")"))
    dff_sel = dff[dff["codcuenca"] == cod] if cod in dff["codcuenca"].values else pd.DataFrame(columns=dff.columns)
    titulo = elegido

if dff_sel.empty:
    st.warning("No hay datos para esta cuenca con los filtros actuales.")
else:
    pivot_usos = (
        dff_sel.pivot_table(
            index="tipo_obra_agr", columns="uso", values="volumen", aggfunc="count", fill_value=0
        )
        .reindex(index=TIPOS_ORDER, fill_value=0)
    )

    usos_unicos = sorted(dff_sel["uso"].dropna().unique())
    tab10 = plt.colormaps["tab10"].resampled(max(len(usos_unicos), 1))

    fig_tipo = go.Figure()
    for i, uso_col in enumerate(pivot_usos.columns):
        r, g, b, _ = tab10(i)
        hex_color = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

        if uso_col in pivot_usos.columns:
            fig_tipo.add_trace(go.Bar(
                x=pivot_usos[uso_col],
                y=pivot_usos.index,
                name=str(uso_col),
                orientation="h",
                marker_color=hex_color,
            ))

    fig_tipo.update_layout(
        barmode="stack",
        title=titulo,
        height=450,
        margin=dict(l=0, r=10, t=50, b=0),
        xaxis_title="Cantidad de obras",
        yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_tipo, use_container_width=True)

st.markdown("---")

# --------------------------------------------------------------------------
# Obras por tipo, cuenca por cuenca
# --------------------------------------------------------------------------
por_cuenca_ord = por_cuenca.copy()
por_cuenca_ord["label"] = (
    por_cuenca_ord["nombre_cuenca"] + " (#" + por_cuenca_ord["codcuenca"].astype(str) + ")"
)
por_cuenca_ord = por_cuenca_ord.sort_values(["cuenca_n1", "n_obras"])

n1_presentes = [n1 for n1 in N1_COLORS if n1 in por_cuenca_ord["cuenca_n1"].unique()]
orden_label_global = por_cuenca_ord["label"].tolist()
altura_todas = len(por_cuenca_ord) * 28 + len(n1_presentes) * 60

st.header("🔢 Cantidad de derechos otorgados por cuenca nivel 2")
fig_obras_todas = px.bar(
    por_cuenca_ord,
    x="n_obras",
    y="label",
    orientation="h",
    facet_row="cuenca_n1",
    category_orders={"cuenca_n1": n1_presentes, "label": orden_label_global},
    color="cuenca_n1",
    color_discrete_map=N1_COLORS,
    text="n_obras",
    labels={"n_obras": "Cantidad de obras", "label": ""},
)
fig_obras_todas.update_traces(textposition="outside")
fig_obras_todas.update_layout(
    height=max(altura_todas, 500), margin=dict(l=0, r=60, t=30, b=0), showlegend=False
)
fig_obras_todas.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
fig_obras_todas.update_yaxes(matches=None)
fig_obras_todas.update_xaxes(matches="x")
st.plotly_chart(fig_obras_todas, use_container_width=True)

st.markdown("---")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Tabla completa
# --------------------------------------------------------------------------
st.subheader("Tabla completa — cuencas nivel 2")
tabla = por_cuenca[["codcuenca", "nombre_cuenca", "cuenca_n1", "area_km2", "volumen", "volumen_embalse", "n_obras"]].reset_index(drop=True)
tabla.columns = ["Código", "Cuenca nivel 2", "Cuenca nivel 1", "Área (km²)", "Volumen (m³)", "Vol. Embalse (m³)", "Obras"]
st.dataframe(
    tabla,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Volumen (m³)": st.column_config.NumberColumn(format="%.0f"),
        "Vol. Embalse (m³)": st.column_config.NumberColumn(format="%.0f"),
        "Área (km²)": st.column_config.NumberColumn(format="%.0f"),
    },
)

st.download_button(
    "Descargar tabla (CSV)",
    tabla.to_csv(index=False).encode("utf-8"),
    file_name="volumen_obras_por_cuenca_n2.csv",
    mime="text/csv",
)

with st.expander("Ver solicitudes individuales (detalle fila por fila)"):
    st.dataframe(dff, use_container_width=True, hide_index=True)

