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

# Orden fijo de tipos de obra (Toma se agrupó con Reservorio: solo 4 casos en todo el país)
TIPOS_ORDER = [
    "Represa Grande", "Represa Mediana", "Represa Chica",
    "Tajamar Grande", "Tajamar Mediano", "Tajamar Chico",
    "Tanque Excavado", "Reservorio/Otros",
]

# Paleta categórica (cuenca nivel 1) — orden fijo, no ciclar colores (pasos "dark" de la paleta)
N1_COLORS = {
    "Río Uruguay": "#3987e5",
    "Río de la Plata": "#d95926",
    "Océano Atlántico": "#199e70",
    "Laguna Merín": "#c98500",
    "Río Negro": "#d55181",
    "Santa Lucía": "#2fa72f",
}
SEQ_SCALE = [  # rampa secuencial (un solo hue, claro -> oscuro) para el mapa
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b",
]

# fondo oscuro para los dos mapas (CartoDB, no necesita token de API)
MAPA_ESTILO = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
MAPA_ESTILO_CHOROPLETH = "carto-darkmatter-nolabels"  # estilo propio de px.choropleth_map


def miles(n):
    """1234567 -> '1.234.567' (separador de miles a la uruguaya)."""
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

    # nombre y área de cada cuenca nivel 2, desde el geojson
    props = pd.DataFrame([feat["properties"] for feat in geojson["features"]])
    props["codcuenca"] = props["codcuenca"].astype(int)
    props = props.rename(columns={"nombre_cue": "nombre_cuenca", "area": "area_km2"})
    props = props[["codcuenca", "nombre_cuenca", "area_km2", "cabecera"]]

    return df, geojson, props


df, geojson, cuencas_meta = load_data()

# nombre de cuenca nivel 2 por código (incluye el 46, que no tiene polígono)
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
    "(Río Uruguay, Río de la Plata, Océano Atlántico, Laguna Merín, "
    "Río Negro, Santa Lucía) + shapefile de cuencas nivel 2 (capa c098), "
    "unidos por el código de cuenca nivel 2. El volumen se asume en m³ "
    "(no viene con unidad explícita en el origen)."
)
if codigos_sin_poligono:
    st.sidebar.caption(
        f"Nota: la cuenca {codigos_sin_poligono} tiene solicitudes registradas "
        "pero no tiene polígono propio en el shapefile provisto, así que no "
        "aparece en el mapa (sí en la tabla y en los rankings)."
    )

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
por_cuenca = (
    dff.groupby("codcuenca")
    .agg(volumen=("volumen", "sum"), n_obras=("volumen", "count"))
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
st.title("💧 Volumen concedido y obras por cuenca nivel 2")
st.caption(
    f"{por_cuenca.shape[0]} cuencas nivel 2 · {len(n1_selected)} de 6 cuencas nivel 1 · "
    f"{len(dff):,} solicitudes".replace(",", ".")
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Volumen total", f"{dff['volumen'].sum() / 1e6:,.1f} hm³".replace(",", "."))
c2.metric("Obras registradas", f"{len(dff):,}".replace(",", "."))
c3.metric("Cuencas nivel 2", f"{por_cuenca.shape[0]}")
c4.metric("Volumen medio / obra", f"{dff['volumen'].mean():,.0f} m³".replace(",", "."))

st.markdown("---")


# --------------------------------------------------------------------------
# Mapa + ranking
# --------------------------------------------------------------------------
col_map, col_rank = st.columns([1.05, 0.95])

with col_map:
    st.subheader("Volumen concedido por cuenca (mapa)")
    map_df = por_cuenca[por_cuenca["codcuenca"].isin(
        [f["properties"]["codcuenca"] for f in geojson["features"]]
    )]
    # Centro y zoom calculados a partir de los límites del propio geojson.
    # Fondo oscuro (CartoDB dark-matter), igual que el mapa de puntos de más abajo.
    lons = [pt[0] for feat in geojson["features"] for ring in feat["geometry"]["coordinates"]
            for poly in (ring if feat["geometry"]["type"] == "MultiPolygon" else [ring])
            for pt in poly]
    lats = [pt[1] for feat in geojson["features"] for ring in feat["geometry"]["coordinates"]
            for poly in (ring if feat["geometry"]["type"] == "MultiPolygon" else [ring])
            for pt in poly]
    center = {"lat": (min(lats) + max(lats)) / 2, "lon": (min(lons) + max(lons)) / 2}

    fig_map = px.choropleth_map(
        map_df,
        geojson=geojson,
        locations="codcuenca",
        featureidkey="properties.codcuenca",
        color="volumen",
        color_continuous_scale=SEQ_SCALE,
        hover_name="nombre_cuenca",
        hover_data={"codcuenca": True, "volumen": ":,.0f", "n_obras": True},
        map_style=MAPA_ESTILO_CHOROPLETH,
        center=center,
        zoom=5.05,
        opacity=0.85,
    )
    fig_map.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        coloraxis_colorbar=dict(title="Volumen (m³)"),
        height=560,
    )
    st.plotly_chart(fig_map, use_container_width=True)

with col_rank:
    st.subheader("Ranking de cuencas por volumen")
    rank_df = por_cuenca.sort_values("volumen", ascending=True).tail(25)
    rank_df["label"] = rank_df["nombre_cuenca"] + " (#" + rank_df["codcuenca"].astype(str) + ")"
    fig_rank = px.bar(
        rank_df,
        x="volumen",
        y="label",
        orientation="h",
        color="cuenca_n1",
        color_discrete_map=N1_COLORS,
        labels={"volumen": "Volumen (m³)", "label": "", "cuenca_n1": "Cuenca nivel 1"},
    )
    fig_rank.update_layout(
        height=560,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig_rank, use_container_width=True)
    st.caption("Top 25 de la selección actual. Ver la tabla completa más abajo.")

st.markdown("---")


# --------------------------------------------------------------------------
# Distribución geográfica de las solicitudes (punto por obra)
# --------------------------------------------------------------------------
st.header("🗺️ Distribución geográfica de las solicitudes")

modo_mapa = st.radio(
    "Colorear puntos por:",
    options=["Tipo de uso", "Volumen"],
    horizontal=True,
)

df_mapa = dff[["lat", "lon", "uso", "volumen"]].copy()
df_mapa["lat"] = pd.to_numeric(df_mapa["lat"], errors="coerce")
df_mapa["lon"] = pd.to_numeric(df_mapa["lon"], errors="coerce")
df_mapa = df_mapa[
    df_mapa["lat"].between(-35.5, -30.0) & df_mapa["lon"].between(-59.5, -53.0)
].dropna(subset=["lat", "lon"])

if df_mapa.empty:
    st.warning("No hay puntos georreferenciados para los filtros seleccionados.")
elif modo_mapa == "Tipo de uso":
    usos_unicos = sorted(df_mapa["uso"].dropna().unique())
    tab10 = plt.colormaps["tab10"].resampled(max(len(usos_unicos), 1))
    color_map = {}
    for i, uso in enumerate(usos_unicos):
        r, g, b, _ = tab10(i)
        color_map[uso] = [int(r * 255), int(g * 255), int(b * 255), 200]
    df_mapa["color"] = df_mapa["uso"].apply(lambda u: color_map.get(u, [150, 150, 150, 180]))

    leyenda_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;'>"
    for i, uso in enumerate(usos_unicos):
        r, g, b, _ = tab10(i)
        hex_c = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
        leyenda_html += (
            f"<span style='background:{hex_c};color:white;"
            f"padding:3px 10px;border-radius:12px;font-size:12px;'>{uso}</span>"
        )
    leyenda_html += "</div>"
    st.markdown(leyenda_html, unsafe_allow_html=True)
    st.caption(f"📍 {miles(len(df_mapa))} registros georreferenciados")

    layer = pdk.Layer(
        "ScatterplotLayer", data=df_mapa,
        get_position=["lon", "lat"], get_color="color",
        get_radius=3000, pickable=True, auto_highlight=True,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=-32.5, longitude=-56.0, zoom=6),
        map_style=MAPA_ESTILO,
        tooltip={"text": "Uso: {uso}"},
    ))

else:  # modo_mapa == "Volumen"
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
        f"<div style='display:flex;align-items:center;gap:12px;"
        f"margin-bottom:12px;font-size:12px;'>"
        f"<span>Volumen:</span>"
        f"<span style='background:{hex_b};color:white;padding:3px 10px;"
        f"border-radius:12px;'>Bajo (&lt;{miles(vol_min)} m³)</span>"
        f"<span style='background:{hex_m};color:white;padding:3px 10px;"
        f"border-radius:12px;'>Medio (~{miles(vol_med)} m³)</span>"
        f"<span style='background:{hex_a};color:white;padding:3px 10px;"
        f"border-radius:12px;'>Alto (&gt;{miles(vol_max)} m³)</span>"
        f"<span style='color:#aaa;'>Tamaño proporcional al volumen</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"📍 {miles(len(df_mapa_vol))} registros con volumen georreferenciados")

    layer = pdk.Layer(
        "ScatterplotLayer", data=df_mapa_vol,
        get_position=["lon", "lat"], get_color="color",
        get_radius="radio", pickable=True, auto_highlight=True,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=-32.5, longitude=-56.0, zoom=6),
        map_style=MAPA_ESTILO,
        tooltip={"text": "Volumen: {volumen} m³\nUso: {uso}"},
    ))

st.markdown("---")


# --------------------------------------------------------------------------
# Detalle por cuenca + resumen por cuenca nivel 1
# --------------------------------------------------------------------------
col_detail, col_n1 = st.columns([1.05, 0.95])

with col_detail:
    st.subheader("Obras por tipo")
    opciones = ["— Total de la selección —"] + [
        f"{row.nombre_cuenca} (#{row.codcuenca})" for row in por_cuenca.itertuples()
    ]
    elegido = st.selectbox("Elegí una cuenca nivel 2 (o dejá el total agregado)", opciones)

    if elegido == opciones[0]:
        tipo_totales = tipo_por_cuenca.sum(axis=0).reindex(TIPOS_ORDER, fill_value=0)
        titulo = "Total de la selección actual"
    else:
        cod = int(elegido.split("#")[-1].rstrip(")"))
        tipo_totales = tipo_por_cuenca.loc[cod].reindex(TIPOS_ORDER, fill_value=0) if cod in tipo_por_cuenca.index else pd.Series(0, index=TIPOS_ORDER)
        titulo = elegido

    fig_tipo = go.Figure(go.Bar(
        x=tipo_totales.values,
        y=tipo_totales.index,
        orientation="h",
        marker_color="#2a78d6",
        text=tipo_totales.values,
        textposition="outside",
    ))
    fig_tipo.update_layout(
        title=titulo,
        height=380,
        margin=dict(l=0, r=10, t=40, b=0),
        xaxis_title="Cantidad de obras",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig_tipo, use_container_width=True)

with col_n1:
    st.subheader("Cuencas nivel 1")
    resumen_n1 = (
        dff.groupby("cuenca_n1")
        .agg(volumen=("volumen", "sum"), obras=("volumen", "count"), cuencas=("codcuenca", "nunique"))
        .reset_index()
        .sort_values("volumen", ascending=False)
    )
    fig_n1 = px.bar(
        resumen_n1.sort_values("volumen"),
        x="volumen", y="cuenca_n1", orientation="h",
        color="cuenca_n1", color_discrete_map=N1_COLORS,
        text=resumen_n1.sort_values("volumen")["obras"].astype(str) + " obras",
        labels={"volumen": "Volumen (m³)", "cuenca_n1": ""},
    )
    fig_n1.update_traces(textposition="outside")
    fig_n1.update_layout(height=380, margin=dict(l=0, r=10, t=10, b=0), showlegend=False)
    st.plotly_chart(fig_n1, use_container_width=True)

st.markdown("---")


# --------------------------------------------------------------------------
# Tabla completa
# --------------------------------------------------------------------------
st.subheader("Tabla completa — cuencas nivel 2")
tabla = por_cuenca[["codcuenca", "nombre_cuenca", "cuenca_n1", "area_km2", "volumen", "n_obras"]].reset_index(drop=True)
tabla.columns = ["Código", "Cuenca nivel 2", "Cuenca nivel 1", "Área (km²)", "Volumen (m³)", "Obras"]
st.dataframe(
    tabla,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Volumen (m³)": st.column_config.NumberColumn(format="%.0f"),
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
