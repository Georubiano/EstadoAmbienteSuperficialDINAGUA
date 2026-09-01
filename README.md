# Balance hídrico por cuenca nivel 2

App de Streamlit: volumen total concedido y cantidad de obras (represas,
tajamares, tanques, reservorios) por cada una de las 48 cuencas nivel 2 de
Uruguay, con mapa, ranking y filtros por cuenca nivel 1.

## Estructura

```
streamlit_app/
├── streamlit_app.py        # la app (esto es lo que corre en Streamlit)
├── prepare_data.py         # ETL: xlsx + shapefile -> data/*.csv y *.geojson
├── requirements.txt        # dependencias de la app (streamlit, pandas, plotly)
├── requirements-prep.txt   # dependencias SOLO de prepare_data.py (geopandas, etc.)
├── raw/                    # acá van los 6 xlsx originales + el shapefile
└── data/                   # salida de prepare_data.py, lo que lee la app
    ├── solicitudes_limpio.csv
    └── cuencas_n2.geojson
```

La app (`streamlit_app.py`) **no** necesita geopandas ni los excels
originales — solo lee los dos archivos livianos de `data/`. Así el deploy
en Streamlit Cloud queda simple y rápido (nada de GDAL).

## Correr en PyCharm / localmente

1. Creá un entorno virtual y activalo.
2. `data/` ya viene con los dos archivos listos para usar (ya corrí
   `prepare_data.py` una vez). Si más adelante cambian los datos de origen,
   volvé a generarlos:

   ```bash
   pip install -r requirements-prep.txt
   python prepare_data.py
   ```

3. Instalá las dependencias de la app y corré:

   ```bash
   pip install -r requirements.txt
   streamlit run streamlit_app.py
   ```

   Se abre en `http://localhost:8501`.

## Desplegar en Streamlit Community Cloud

1. Subí esta carpeta a un repo de GitHub (público, o privado si tenés plan
   pago). Asegurate de que `data/solicitudes_limpio.csv` y
   `data/cuencas_n2.geojson` **sí** estén commiteados — son los que lee la
   app en producción. `raw/` no hace falta subirla (son los xlsx/shapefile
   originales, ya no se usan en el deploy).
2. Entrá a [share.streamlit.io](https://share.streamlit.io), conectá tu
   cuenta de GitHub y elegí el repo.
3. Main file path: `streamlit_app.py` (ajustá la ruta si esta carpeta no
   queda en la raíz del repo, ej. `streamlit_app/streamlit_app.py`).
4. Deploy. Con `requirements.txt` alcanza — no hace falta `requirements-prep.txt`
   en el deploy.

## Notas sobre los datos

- El campo **Volumen** se tomó tal cual figura en las planillas de origen,
  sin unidad explícita (se asume m³, convención habitual de DINAGUA).
- Los tipos de obra **Reservorio** y **Toma** (4 solicitudes en todo el
  país) se agruparon como "Reservorio/Otros" para el desglose por tipo.
- La cuenca de código **46** (Laguna Merín) tiene 12 solicitudes pero no
  tiene polígono propio en el shapefile provisto (`c098Polygon.shp`), así
  que no aparece en el mapa — sí en la tabla y en los rankings.
- El mapa usa `map_style="white-bg"` (fondo en blanco, sin tiles de
  ningún proveedor externo) para no depender de servicios de mapas de
  terceros ni de tokens de API.
