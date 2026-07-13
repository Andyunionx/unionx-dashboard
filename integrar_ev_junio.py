# -*- coding: utf-8 -*-
"""
Integra la facturación de El Volcán junio-2026 (archivo de Nicole, hoja 'raw')
al histórico, PISANDO El Volcán junio desde W23 en adelante.

El histórico tenía El Volcán jun incompleto (solo W23, $5,89M). El archivo trae
junio completo (W23-27, $15,6M). Se eliminan las filas El Volcán 2026-jun del
histórico y se reemplazan por las del archivo.

Uso:  python integrar_ev_junio.py           # dry-run
      python integrar_ev_junio.py --apply   # aplica (backup .bak_ev)
"""
import argparse, shutil
from pathlib import Path
import pandas as pd
import openpyxl

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"
EV = Path("C:/Users/andre/AppData/Local/Temp/claude/g--Mi-unidad-TRABAJO-RESPALDO-OPERACIONES-UNION-X---IA/dff4caa3-b773-4c75-b3ac-1164eef810c4/scratchpad/ev_junio.xlsx")

MAP = {
    'Tipo Movimiento': 'tipo_movimiento', 'Bodega': 'bodega', 'Documento': 'documento',
    'Fecha Documento': 'fecha_documento', 'Pedido': 'pedido', 'Estado Pedido': 'estado_pedido',
    'Tipo Despacho': 'tipo_despacho', 'SKU': 'sku', 'Canal': 'canal', 'Fecha Venta': 'fecha_venta',
    'Hora Venta': 'hora_venta', 'Producto': 'producto', 'Categoría macro': 'categoria_macro',
    'Categoría padre': 'categoria_padre', 'Categoría hijo': 'categoria_hijo',
    'Categoría comercial': 'categoria_comercial', 'Estado SKU': 'estado_sku', 'Pack': 'pack',
    'Marca': 'marca', 'Proveedor': 'proveedor', 'Tipo Marca': 'tipo_marca', 'Tipo Compra': 'tipo_compra',
    'Tipo Negocio': 'tipo_negocio', 'KAM': 'kam', 'Estado Canal': 'estado_canal',
    'Hora venta': 'hora_venta_num', 'Cantidad': 'cantidad', 'Venta bruta': 'venta_bruta',
    'Costo Unitario': 'costo_unitario', 'Costo Total': 'costo_total', 'Margen Front': 'margen_front',
    'Comision %': 'comision_pct', 'Comisión': 'comision', 'Logística': 'logistica',
    'Marketing': 'marketing', 'Mg final': 'margen_final',
}
NUM = ['hora_venta_num', 'cantidad', 'venta_bruta', 'costo_unitario', 'costo_total',
       'margen_front', 'comision_pct', 'comision', 'logistica', 'marketing', 'margen_final']


def cargar_ev():
    ws = openpyxl.load_workbook(EV, read_only=True, data_only=True)['raw']
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(c).strip() if c else '' for c in rows[0]]
    df = pd.DataFrame(rows[1:], columns=hdr)
    df = df[df['Canal'].astype(str).str.strip() != '']
    out = pd.DataFrame()
    for disp, snake in MAP.items():
        out[snake] = df[disp] if disp in df.columns else ''
    for c in NUM:
        out[c] = pd.to_numeric(out[c], errors='coerce').fillna(0)
    # fecha_venta / fecha_documento -> 'YYYY-MM-DD'
    fv = pd.to_datetime(out['fecha_venta'], errors='coerce')
    out['fecha_venta'] = fv.dt.strftime('%Y-%m-%d')
    out['fecha_documento'] = pd.to_datetime(out['fecha_documento'], errors='coerce').dt.strftime('%Y-%m-%d').fillna(out['fecha_venta'])
    # recomputar fechas desde fecha_venta (canónico)
    out['anio_venta'] = fv.dt.year.fillna(0).astype('int64')
    out['mes_venta'] = fv.dt.month.fillna(0).astype('int64')
    out['semana_venta'] = fv.dt.isocalendar().week.fillna(0).astype('int64')
    out['dia_venta_weekday'] = fv.dt.weekday
    DIAS = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
    out['dia_semana'] = out['dia_venta_weekday'].map(DIAS).fillna('')
    out = out.drop(columns=['dia_venta_weekday'])
    # derivadas faltantes
    out['venta_neta'] = out['venta_bruta'] / 1.19
    out['es_despacho'] = False
    out['pedido_marketplace'] = ''
    out['yuju_pack_id'] = ''
    return out


def main(apply=False):
    ev = cargar_ev()
    print(f"[EV Nicole] {len(ev)} filas | canal={ev['canal'].unique().tolist()} | "
          f"semanas={sorted(ev['semana_venta'].unique().tolist())} | bruta ${ev['venta_bruta'].sum()/1e6:.2f}M")
    print(f"  tipo_marca: {ev['tipo_marca'].value_counts().to_dict()}")

    h = pd.read_parquet(HIST)
    cat_cols = [c for c in h.columns if str(h[c].dtype) == 'category']
    for c in cat_cols:
        h[c] = h[c].astype(object)
    # alinear columnas de ev al esquema del histórico
    for c in h.columns:
        if c not in ev.columns:
            ev[c] = False if c == 'es_despacho' else (0 if pd.api.types.is_numeric_dtype(h[c].dtype) else '')
    ev = ev[h.columns.tolist()]
    for c in h.columns:
        if pd.api.types.is_numeric_dtype(h[c].dtype):
            ev[c] = pd.to_numeric(ev[c], errors='coerce').fillna(0).astype(h[c].dtype)
        elif h[c].dtype == bool:
            ev[c] = ev[c].astype(bool)
        else:
            ev[c] = ev[c].astype(str).replace('nan', '')

    rm = (h['canal'].astype(str).str.lower().str.contains('volcan')) & (h['anio_venta'] == 2026) & (h['mes_venta'] == 6)
    print(f"[hist] El Volcán jun ACTUAL: {int(rm.sum())} filas / ${h.loc[rm,'venta_bruta'].astype(float).sum()/1e6:.2f}M  -> se elimina")
    h_new = pd.concat([h[~rm], ev], ignore_index=True)
    for c in cat_cols:
        h_new[c] = h_new[c].astype('category')
    assert set(h_new.columns) == set(h.columns), "columnas cambiaron"
    evn = h_new[(h_new['canal'].astype(str).str.lower().str.contains('volcan')) & (h_new['anio_venta'] == 2026) & (h_new['mes_venta'] == 6)]
    print(f"[hist] El Volcán jun NUEVO: {len(evn)} filas / ${evn['venta_bruta'].astype(float).sum()/1e6:.2f}M")
    print(f"[hist] total filas: {len(h):,} -> {len(h_new):,}")
    if not apply:
        print("\n[DRY-RUN] no se escribió nada.")
        return
    shutil.copy2(str(HIST), str(HIST) + ".bak_ev")
    h_new.to_parquet(HIST, index=False, compression='zstd')
    print(f"\n[OK] aplicado. Backup .bak_ev  ({len(h_new):,} filas)")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    main(**vars(ap.parse_args()))
