"""
ETL: Convierte las 6 planillas de solicitudes de aprovechamiento hídrico
(una por cuenca nivel 1) en el archivo liviano 'solicitudes_limpio.csv'
para su uso en análisis y dashboards de Streamlit.
"""

from pathlib import Path
import pandas as pd

# Directorios de trabajo
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Mapeo de archivos Excel por cuenca de nivel 1 y su respectiva hoja
RAW_FILES = {
    "Río Uruguay":       ("1 Rio Uruguay.xlsx", "10"),
    "Río de la Plata":   ("2 Rio de la Plata.xlsx", 0),
    "Océano Atlántico":  ("3 Oceano Atlantico.xlsx", 0),
    "Laguna Merín":      ("4 Laguna Merin.xlsx", 0),
    "Río Negro":         ("5 Rio Negro.xlsx", 0),
    "Santa Lucía":       ("6 Santa Lucia.xlsx", 0),
}

# Diccionarios de normalización de columnas y agrupamientos
RENAME_MAP = {"Cuencas ": "Cuenca de nivel 2"}
TIPO_OBRA_AGRUPADO = {"Toma": "Reservorio/Otros", "Reservorio": "Reservorio/Otros"}

def unify_solicitudes() -> pd.DataFrame:
    frames = []

    # 1. Leer y unificar los archivos de las 6 cuencas
    for cuenca_n1, (filename, sheet) in RAW_FILES.items():
        path = ROOT / filename
        if not path.exists():
            path = ROOT / "raw" / filename

        if path.exists():
            df = pd.read_excel(path, sheet_name=sheet)
            df = df.rename(columns=RENAME_MAP)
            df["cuenca_n1"] = cuenca_n1
            frames.append(df)
        else:
            print(f"Advertencia: No se encontró el archivo {filename}")

    if not frames:
        raise FileNotFoundError("No se encontró ningún archivo de cuenca de origen.")

    full = pd.concat(frames, ignore_index=True, sort=False)

    # 2. Limpieza y conversión de tipos de datos
    full["Tipo de Obra"] = full["Tipo de Obra"].astype(str).str.strip()
    full.loc[full["Tipo de Obra"].isin(["nan", "None", ""]), "Tipo de Obra"] = None

    full["Codigo Cuencas de nivel 2"] = pd.to_numeric(
        full["Codigo Cuencas de nivel 2"], errors="coerce"
    ).astype("Int64")

    full["Volumen"] = pd.to_numeric(full["Volumen"], errors="coerce")
    if "Volúmen de Embalse" in full.columns:
        full["Volúmen de Embalse"] = pd.to_numeric(full["Volúmen de Embalse"], errors="coerce")

    # 3. Selección y renombrado de columnas clave
    cols = {
        "cuenca_n1": "cuenca_n1",
        "Codigo Cuencas de nivel 2": "codcuenca",
        "Tipo de Obra": "tipo_obra",
        "Volumen": "volumen",
        "Volúmen de Embalse": "Volumen de embalse",
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

    # Crear columna agrupada para el tipo de obra si aplica
    out["tipo_obra_agr"] = out["tipo_obra"].replace(TIPO_OBRA_AGRUPADO)

    # Filtrar registros que contengan código de cuenca válido
    out = out.dropna(subset=["codcuenca"])
    out["codcuenca"] = out["codcuenca"].astype(int)

    return out

if __name__ == "__main__":
    print("Iniciando proceso de unificación y limpieza...")
    solicitudes = unify_solicitudes()

    # Guardar en la carpeta data/ y en la raíz según convenga
    out_csv = DATA_DIR / "solicitudes_limpio.csv"
    solicitudes.to_csv(out_csv, index=False, encoding="utf-8")
    solicitudes.to_csv(ROOT / "solicitudes_limpio.csv", index=False, encoding="utf-8")

    print(f"¡Éxito! Se ha generado/sobrescrito '{out_csv}' con {len(solicitudes)} registros procesados.")