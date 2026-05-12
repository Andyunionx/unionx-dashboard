#!/usr/bin/env python3
"""
Procesador Centro de Costos: cruza libro de compras subido (SII / cartola) con
el Excel de memoria (mapping proveedor → cuenta contable) y genera la lista
de movimientos LISTOS para digitalizar en Odoo.

Pasos del flujo según Andrés:
  1. Análisis libro compras → cargar Excel del SII (manual upload)
  2. Memoria de cuentas contables → Excel con relaciones proveedor↔cuenta
  3. Cartolas bancarias → cruzar pagos
  4. Generar propuesta de digitalización en Odoo (no escribe automático,
     genera archivo para revisión + botón "Aplicar a Odoo" en la app)

Inputs (uploads manuales):
  - data/contabilidad/centro_costos/libros_compras/libro_*.xlsx
  - data/contabilidad/centro_costos/memoria_cuentas.xlsx
  - data/contabilidad/centro_costos/cartolas_bancarias/cartola_*.xlsx

Outputs:
  - data/contabilidad/centro_costos/movimientos_procesados.parquet
  - data/contabilidad/centro_costos/pendientes_revision.parquet
  - data/contabilidad/centro_costos/resumen.json
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
CC_DIR = PROJECT_ROOT / "data" / "contabilidad" / "centro_costos"
LIBROS_DIR = CC_DIR / "libros_compras"
CARTOLAS_DIR = CC_DIR / "cartolas_bancarias"
MEMORIA_FILE = CC_DIR / "memoria_cuentas.xlsx"

CC_DIR.mkdir(parents=True, exist_ok=True)
LIBROS_DIR.mkdir(parents=True, exist_ok=True)
CARTOLAS_DIR.mkdir(parents=True, exist_ok=True)


def _normalizar_rut(rut) -> str:
    """Normaliza RUT chileno: quita puntos/guiones, deja '12345678-9'."""
    if not rut:
        return ""
    s = str(rut).replace(".", "").replace(" ", "").upper().strip()
    if not s:
        return ""
    if "-" not in s and len(s) > 1:
        s = f"{s[:-1]}-{s[-1]}"
    return s


def _cargar_libros_compras() -> pd.DataFrame:
    """Lee todos los Excels del SII subidos manualmente.

    Formato esperado del SII (libro de compras electrónico):
      Tipo Doc, Folio, RUT Proveedor, Razón Social, Fecha, Monto Neto, IVA, Monto Total
    """
    frames = []
    for archivo in sorted(LIBROS_DIR.glob("*.xlsx")):
        try:
            df = pd.read_excel(archivo)
            df["__archivo_origen"] = archivo.name
            frames.append(df)
            print(f"  + {archivo.name}: {len(df)} filas", flush=True)
        except Exception as e:
            print(f"  ! Error leyendo {archivo.name}: {e}", flush=True)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # Normalizar columnas más comunes (varía según export del SII)
    rename_map = {}
    for col in df.columns:
        c = str(col).strip().upper()
        if "RUT" in c and "PROV" in c:
            rename_map[col] = "rut_proveedor"
        elif c in ("RUT", "RUT PROVEEDOR"):
            rename_map[col] = "rut_proveedor"
        elif "RAZON" in c or "RAZÓN" in c or c == "RAZON SOCIAL":
            rename_map[col] = "razon_social"
        elif "FOLIO" in c:
            rename_map[col] = "folio"
        elif "FECHA" in c:
            rename_map[col] = "fecha"
        elif "MONTO TOTAL" in c or c == "TOTAL":
            rename_map[col] = "monto_total"
        elif "MONTO NETO" in c or c == "NETO":
            rename_map[col] = "monto_neto"
        elif c == "IVA" or "I.V.A" in c:
            rename_map[col] = "iva"
        elif "TIPO DOC" in c or c == "TIPO":
            rename_map[col] = "tipo_doc"
    df = df.rename(columns=rename_map)
    if "rut_proveedor" in df.columns:
        df["rut_proveedor_norm"] = df["rut_proveedor"].apply(_normalizar_rut)
    return df


def _cargar_memoria() -> pd.DataFrame:
    """Lee el Excel de memoria proveedor → cuenta contable.

    Formato esperado (flexible):
      RUT Proveedor | Razón Social | Cuenta Contable | Centro Costo | Tipo
    """
    if not MEMORIA_FILE.exists():
        print(f"  ! No existe {MEMORIA_FILE.name} — sube el Excel de memoria",
              flush=True)
        return pd.DataFrame()
    try:
        df = pd.read_excel(MEMORIA_FILE)
        rename_map = {}
        for col in df.columns:
            c = str(col).strip().upper()
            if "RUT" in c:
                rename_map[col] = "rut_proveedor"
            elif "RAZON" in c or "RAZÓN" in c or "PROVEEDOR" in c or "NOMBRE" in c:
                rename_map[col] = "razon_social"
            elif "CUENTA" in c and "CONTAB" in c:
                rename_map[col] = "cuenta_contable"
            elif "CUENTA" in c:
                rename_map[col] = "cuenta_contable"
            elif "CENTRO" in c and "COSTO" in c:
                rename_map[col] = "centro_costo"
            elif c == "CC":
                rename_map[col] = "centro_costo"
            elif "TIPO" in c or "CATEG" in c:
                rename_map[col] = "tipo_gasto"
        df = df.rename(columns=rename_map)
        if "rut_proveedor" in df.columns:
            df["rut_proveedor_norm"] = df["rut_proveedor"].apply(_normalizar_rut)
        print(f"  + memoria_cuentas.xlsx: {len(df)} mappings", flush=True)
        return df
    except Exception as e:
        print(f"  ! Error leyendo memoria: {e}", flush=True)
        return pd.DataFrame()


def _cargar_cartolas() -> pd.DataFrame:
    """Lee cartolas bancarias subidas. Formato variable por banco."""
    frames = []
    for archivo in sorted(CARTOLAS_DIR.glob("*.xlsx")):
        try:
            df = pd.read_excel(archivo)
            df["__archivo_origen"] = archivo.name
            df["__banco"] = archivo.stem.split("_")[0] if "_" in archivo.stem else "desconocido"
            frames.append(df)
            print(f"  + {archivo.name}: {len(df)} movimientos", flush=True)
        except Exception as e:
            print(f"  ! Error leyendo cartola {archivo.name}: {e}", flush=True)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # Normalizar columnas comunes
    rename_map = {}
    for col in df.columns:
        c = str(col).strip().upper()
        if "FECHA" in c:
            rename_map[col] = "fecha"
        elif "DESCRIPCION" in c or "DESCRIPCIÓN" in c or "GLOSA" in c or "DETALLE" in c:
            rename_map[col] = "descripcion"
        elif c == "MONTO" or "ABONO" in c or "CARGO" in c:
            rename_map[col] = "monto"
        elif "REFERENCIA" in c or "RUT" in c:
            rename_map[col] = "referencia"
    return df.rename(columns=rename_map)


def main():
    print(f"=== Extract Contabilidad Centro Costos — {datetime.now().isoformat()} ===\n",
          flush=True)

    print("[1] Cargando libros de compras...", flush=True)
    df_libro = _cargar_libros_compras()
    print(f"    Total: {len(df_libro):,} líneas\n", flush=True)

    print("[2] Cargando memoria de cuentas contables...", flush=True)
    df_memoria = _cargar_memoria()
    print(f"    Total: {len(df_memoria):,} mappings\n", flush=True)

    print("[3] Cargando cartolas bancarias...", flush=True)
    df_cartolas = _cargar_cartolas()
    print(f"    Total: {len(df_cartolas):,} movimientos\n", flush=True)

    if df_libro.empty:
        print("⏳ Sin libro de compras cargado. Subir Excel a "
              f"{LIBROS_DIR.relative_to(PROJECT_ROOT)}", flush=True)
        return 0

    # ─── 4. CRUZAR libro × memoria ───────────────────────────────────────
    print("[4] Cruzando libro de compras con memoria...", flush=True)
    if not df_memoria.empty and "rut_proveedor_norm" in df_libro.columns:
        df_merged = df_libro.merge(
            df_memoria[["rut_proveedor_norm", "cuenta_contable",
                         "centro_costo", "tipo_gasto"]],
            on="rut_proveedor_norm", how="left",
        )
    else:
        df_merged = df_libro.copy()
        df_merged["cuenta_contable"] = None
        df_merged["centro_costo"] = None
        df_merged["tipo_gasto"] = None

    # Marcar listos vs pendientes
    df_merged["listo_para_odoo"] = df_merged["cuenta_contable"].notna()
    df_listos = df_merged[df_merged["listo_para_odoo"]].copy()
    df_pendientes = df_merged[~df_merged["listo_para_odoo"]].copy()

    # ─── 5. CRUZAR con cartola para conciliación de pagos ────────────────
    if not df_cartolas.empty and "monto_total" in df_listos.columns:
        # Cruce básico por monto (mejorable con fecha + RUT)
        montos_cartola = df_cartolas[["monto"]].copy() if "monto" in df_cartolas.columns else None
        df_listos["pagado_en_cartola"] = False
        if montos_cartola is not None and not montos_cartola.empty:
            montos_set = set(montos_cartola["monto"].abs().round(0).tolist())
            df_listos["pagado_en_cartola"] = (
                df_listos["monto_total"].abs().round(0).isin(montos_set)
            )

    # Guardar outputs
    df_listos.to_parquet(CC_DIR / "movimientos_procesados.parquet", index=False)
    df_pendientes.to_parquet(CC_DIR / "pendientes_revision.parquet", index=False)
    print(f"    Listos para Odoo: {len(df_listos):,}", flush=True)
    print(f"    Pendientes (sin cuenta contable): {len(df_pendientes):,}", flush=True)

    # Resumen
    monto_total_mes = df_libro["monto_total"].sum() if "monto_total" in df_libro.columns else 0
    monto_listo = df_listos["monto_total"].sum() if "monto_total" in df_listos.columns else 0
    by_cc = (df_listos.groupby("centro_costo")["monto_total"].sum().to_dict()
              if not df_listos.empty and "centro_costo" in df_listos.columns else {})
    by_cuenta = (df_listos.groupby("cuenta_contable")["monto_total"].sum()
                            .sort_values(ascending=False).head(15).to_dict()
                  if not df_listos.empty and "cuenta_contable" in df_listos.columns else {})

    resumen = {
        "generado_en": datetime.now().isoformat(),
        "libros_compras_archivos": len(list(LIBROS_DIR.glob("*.xlsx"))),
        "lineas_libro_compras": len(df_libro),
        "memoria_mappings": len(df_memoria),
        "cartolas_archivos": len(list(CARTOLAS_DIR.glob("*.xlsx"))),
        "movimientos_cartola": len(df_cartolas),
        "listos_para_odoo": len(df_listos),
        "pendientes_revision": len(df_pendientes),
        "monto_total_libro_clp": round(monto_total_mes, 0),
        "monto_listo_clp": round(monto_listo, 0),
        "monto_pendiente_clp": round(monto_total_mes - monto_listo, 0),
        "monto_por_centro_costo": {str(k): round(v, 0) for k, v in by_cc.items()},
        "top_15_cuentas_contables": [
            {"cuenta": str(k), "monto": round(v, 0)} for k, v in by_cuenta.items()
        ],
    }
    with open(CC_DIR / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n=== RESUMEN ===")
    print(f"  Líneas libro compras: {len(df_libro):,}")
    print(f"  Listos para digitalizar en Odoo: {len(df_listos):,} "
          f"(${monto_listo:,.0f} CLP)")
    print(f"  Pendientes (sin cuenta contable): {len(df_pendientes):,}")
    print(f"  → Agregar al Excel memoria_cuentas.xlsx los RUTs faltantes")
    print(f"\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
