"""Genera data/comex/maestra_sabana.parquet — sábana SKU x embarque
de los embarques que ESTÁN POR LLEGAR (Seimex stage: Por Embarcar / En tránsito).

Replica el formato de la Maestra del Drive con detalle por SKU.

Fuentes:
  - data/comex/Maestra Importaciones V2...xlsx (sheet 'Maestra')
  - Seimex API (estado y ETA actualizados)
  - Odoo (enrich: nombre producto, default_code si falta SKU)

Output:
  - data/comex/maestra_sabana.parquet
  - data/comex/maestra_sabana_resumen.json (metadata: timestamp, n_embarques, etc.)
"""
import os, re, sys, json
from datetime import datetime
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, ".")
from seimex_api import SeimexAPI, SeimexAPIError

ROOT = Path(__file__).parent
MAESTRA = ROOT / "data" / "comex" / "Maestra Importaciones V2.backup_20260515_1910_pre0309.xlsx"
OUT_PARQUET = ROOT / "data" / "comex" / "maestra_sabana.parquet"
OUT_RESUMEN = ROOT / "data" / "comex" / "maestra_sabana_resumen.json"

# Stages Seimex que cuentan como "por llegar"
STAGES_POR_LLEGAR = {"Por Embarcar", "En tránsito"}


def codigo_embarque(s):
    """Extrae '0604' de 'PI0604' / '26TP0604' / etc."""
    if not s: return None
    m = re.search(r"PI(\d{4})", str(s).upper())
    if m: return m.group(1)
    m = re.search(r"26TP(\d{4})", str(s).upper())
    return m.group(1) if m else None


def main():
    # 1. Cargar Maestra
    print("[1/4] Cargando Maestra...")
    maes = pd.read_excel(MAESTRA, sheet_name='Maestra')
    maes.columns = [str(c).strip() for c in maes.columns]
    maes['N° Embarque'] = maes['N° Embarque'].astype(str).str.strip()
    maes['cod'] = maes['N° Embarque'].apply(codigo_embarque)
    maes = maes[maes['cod'].notna()]
    print(f"    Filas Maestra: {len(maes)}, embarques únicos: {maes['cod'].nunique()}")

    # 2. Consultar Seimex para saber qué embarques están "por llegar"
    print("[2/4] Consultando Seimex API...")
    try:
        api = SeimexAPI()
        ops = api.get_operations()
    except SeimexAPIError as e:
        print(f"    ⚠️  Seimex API falló: {e}")
        ops = []

    seimex_por_cod = {}
    for op in ops:
        cod = codigo_embarque(op.get("reference_number")) or codigo_embarque(op.get("product"))
        if not cod: continue
        seimex_por_cod[cod] = {
            "stage": op.get("stage", {}).get("name") if isinstance(op.get("stage"), dict) else None,
            "eta": op.get("eta"),
            "port_origin": op.get("port_origin"),
            "has_incident": op.get("has_incident"),
            "quoted_freight_usd": op.get("quoted_freight_value"),
            "booking": op.get("booking"),
            "departure_confirmed": op.get("departure_confirmed"),
            "reference_seimex": op.get("reference_number"),
        }
    print(f"    Embarques Seimex: {len(seimex_por_cod)}")

    # 3. Filtrar Maestra solo a los que están "por llegar"
    print("[3/4] Filtrando por estado 'por llegar'...")
    cods_por_llegar = {c for c, d in seimex_por_cod.items() if d["stage"] in STAGES_POR_LLEGAR}
    print(f"    Códigos por llegar (Seimex): {sorted(cods_por_llegar)}")

    df = maes[maes['cod'].isin(cods_por_llegar)].copy()
    print(f"    Filas sábana: {len(df)} (de {len(maes)} totales)")

    # 4. Enrich con info Seimex
    df['Estado_Seimex'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('stage'))
    df['ETA'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('eta'))
    df['Puerto'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('port_origin'))
    df['Flete_USD_emb'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('quoted_freight_usd'))
    df['Booking_Seimex'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('booking'))
    df['Incident_Seimex'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('has_incident'))
    df['Ref_Seimex'] = df['cod'].map(lambda c: seimex_por_cod.get(c, {}).get('reference_seimex'))

    # 5. Columnas finales en orden tipo sábana Drive
    cols_orden = [
        'N° Embarque', 'No', 'Model', 'SKU', 'NOMBRE',
        'QTY', 'Cost Unit', 'New. Unit Cost', 'Costo FOB', 'Flete', 'CIF',
        'Total CLP', 'Total Costo Landed', 'Costo Neto Unitario',
        'Costo Maestra', 'ETA', 'Estado_Seimex', 'Puerto',
        'Flete_USD_emb', 'Booking_Seimex', 'Incident_Seimex', 'Ref_Seimex', 'PO',
    ]
    cols_finales = [c for c in cols_orden if c in df.columns]
    df_final = df[cols_finales].copy()
    df_final = df_final.sort_values(['N° Embarque', 'No'], na_position='last')

    # 6. Persistir
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_final.to_parquet(OUT_PARQUET, index=False)
    resumen = {
        "generado_en": datetime.now().isoformat(),
        "filas": len(df_final),
        "embarques_unicos": int(df_final['N° Embarque'].nunique()),
        "embarques": sorted(df_final['N° Embarque'].dropna().astype(str).unique().tolist()),
        "stages_incluidos": sorted(STAGES_POR_LLEGAR),
        "fuente_maestra": MAESTRA.name,
        "skus_unicos": int(df_final['SKU'].nunique()),
    }
    OUT_RESUMEN.write_text(json.dumps(resumen, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

    print(f"\n[4/4] ✅ Generado:")
    print(f"    {OUT_PARQUET}")
    print(f"    {OUT_RESUMEN}")
    print(f"\nResumen:")
    print(f"  Filas: {resumen['filas']}")
    print(f"  Embarques: {resumen['embarques_unicos']}")
    print(f"  SKUs únicos: {resumen['skus_unicos']}")
    print(f"  Embarques incluidos: {resumen['embarques']}")
    return df_final


if __name__ == "__main__":
    main()
