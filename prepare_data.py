"""
ETL: convierte las 6 planillas de solicitudes de aprovechamiento hídrico
(una por cuenca nivel 1) + el shapefile de cuencas nivel 2 en los dos
archivos livianos que consume streamlit_app.py:

    data/solicitudes_limpio.csv
    data/cuencas_n2.geojson

Se corre UNA sola vez (o cada vez que cambien los datos de origen).
La app de Streamlit en sí no necesita geopandas ni los xlsx originales,
solo estos dos archivos de salida — así el deploy queda liviano.

Uso:
    python prepare_data.py

Requiere los archivos originales en la carpeta raw/ (ver RAW_FILES abajo).
Dependencias de este script (no las necesita streamlit_app.py):
    pip install pandas openpyxl geopandas shapely
"""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "raw"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Un excel por cuenca nivel 1. (nombre_hoja=0 -> primera hoja del archivo)
RAW_FILES = {
    "Río Uruguay":       ("1_Rio_Uruguay_procesado.xlsx", "10"),
    "Río de la Plata":   ("2_Rio_de_la_Plata_procesado.xlsx", 0),
    "Océano Atlántico":  ("3_Oceano_Atlantico_procesado.xlsx", 0),
    "Laguna Merín":      ("4_Laguna_Merin_procesado.xlsx", 0),
    "Río Negro":         ("5_Rio_Negro_procesado.xlsx", 0),
    "Santa Lucía":       ("6_Santa_Lucia_procesado.xlsx", 0),
}
SHAPEFILE = RAW_DIR / "c098Polygon.shp"  # junto con .shx / .dbf / .prj / .cst

# En la planilla de Laguna Merín la columna de cuenca nivel 2 vino con otro nombre
RENAME_MAP = {"Cuencas ": "Cuenca de nivel 2"}

# 4 solicitudes en todo el país son "Toma" -> se agrupan con Reservorio
TIPO_OBRA_AGRUPADO = {"Toma": "Reservorio/Otros", "Reservorio": "Reservorio/Otros"}


def unify_solicitudes() -> pd.DataFrame:
    """Une las 6 planillas en un único DataFrame, una fila por solicitud/obra."""
    frames = []
    for cuenca_n1, (filename, sheet) in RAW_FILES.items():
        path = RAW_DIR / filename
        df = pd.read_excel(path, sheet_name=sheet)
        df = df.rename(columns=RENAME_MAP)
        df["cuenca_n1"] = cuenca_n1
        frames.append(df)

    full = pd.concat(frames, ignore_index=True, sort=False)

    # limpieza
    full["Tipo de Obra"] = full["Tipo de Obra"].astype(str).str.strip()
    full.loc[full["Tipo de Obra"].isin(["nan", "None", ""]), "Tipo de Obra"] = None
    full["Codigo Cuencas de nivel 2"] = pd.to_numeric(
        full["Codigo Cuencas de nivel 2"], errors="coerce"
    ).astype("Int64")
    full["Volumen"] = pd.to_numeric(full["Volumen"], errors="coerce")

    cols = {
        "cuenca_n1": "cuenca_n1",
        "Codigo Cuencas de nivel 2": "codcuenca",
        "Tipo de Obra": "tipo_obra",
        "Volumen": "volumen",
        "Departamento": "departamento",
        "Uso": "uso",
        "Destino": "destino",
        "Latitud": "lat",
        "Longitud": "lon",
        "Estado": "estado",
        "Accion Solicitud": "accion_solicitud",
        "Tipo Resolución": "tipo_resolucion",
        "Curso a Utilizar": "curso",
        "Área de Cuenca": "area_cuenca_ha",
    }
    present = {k: v for k, v in cols.items() if k in full.columns}
    out = full[list(present.keys())].rename(columns=present)
    out["tipo_obra_agr"] = out["tipo_obra"].replace(TIPO_OBRA_AGRUPADO)

    out = out.dropna(subset=["codcuenca"])
    out["codcuenca"] = out["codcuenca"].astype(int)
    return out


def build_geojson() -> dict:
    """Lee el shapefile de cuencas nivel 2 y lo simplifica para uso web."""
    gdf = gpd.read_file(SHAPEFILE)
    gdf["codcuenca"] = gdf["codcuenca"].astype(int)
    gdf["nombre_cue"] = gdf["nombre_cue"].str.strip()
    gdf["cabecera"] = gdf["cabecera"].astype(int)
    # simplifica la geometría (menos vértices) para que el geojson sea liviano
    gdf["geometry"] = gdf["geometry"].simplify(0.0008, preserve_topology=True)
    return json.loads(gdf.to_json())


def main():
    print("Uniendo las 6 planillas de solicitudes...")
    solicitudes = unify_solicitudes()
    out_csv = DATA_DIR / "solicitudes_limpio.csv"
    solicitudes.to_csv(out_csv, index=False)
    print(f"  -> {out_csv}  ({len(solicitudes):,} filas)".replace(",", "."))

    print("Convirtiendo el shapefile de cuencas nivel 2 a GeoJSON...")
    geojson = build_geojson()
    out_geojson = DATA_DIR / "cuencas_n2.geojson"
    with open(out_geojson, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False)
    print(f"  -> {out_geojson}  ({len(geojson['features'])} cuencas)")

    codigos_datos = set(solicitudes["codcuenca"])
    codigos_shp = {feat["properties"]["codcuenca"] for feat in geojson["features"]}
    faltantes = sorted(codigos_datos - codigos_shp)
    if faltantes:
        print(
            f"  Aviso: los códigos de cuenca {faltantes} tienen solicitudes "
            "pero no tienen polígono en el shapefile (no van a aparecer en el mapa)."
        )

    print("Listo.")


if __name__ == "__main__":
    main()
