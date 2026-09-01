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
        margin=dict(l=0, r=10, t=50, b=0),
        xaxis_title="Cantidad de obras",
        yaxis=dict(autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_tipo, use_container_width=True)

st.markdown("---")