#!/usr/bin/env python3
"""
Sincroniza ventas CMR (fidelización) desde Google Sheet a Turso.

Sheet: 'Base CMR 2026' (owner: nicole@unionx.cl)
ID: 1YAGv-9kqrLWo1wGWzmqlisYJk3-Wuo5r4JmFWUazAiM

Flujo:
1. Lee filas del sheet (≥ 2026-04-01).
2. Match contra Turso: (fecha_venta, sku, canal IN ('UnionX web','Shopify'), venta_bruta=0).
3. UPDATE las filas matched:
   - canal = 'CMR'
   - tipo_negocio = 'Fidelización'
   - venta_bruta = Venta CMR Bruto (PVP)
   - venta_neta = Venta CMR Neto
   - margen_front = venta_neta - costo_total (recalculado)
   - margen_final = margen_front (comision/logistica/marketing en 0)
   (Comisión y envío CMR quedan FUERA del registro: por ahora solo venta y costo → margen directo)
4. Reporta no-matches (CMR sheet sin equivalente en Turso) y duplicates.

Modos:
- DRY_RUN=1 (default): no UPDATE, solo reporta qué haría.
- DRY_RUN=0: ejecuta UPDATE.

Output:
- data/cmr/cmr_matches.parquet (auditoria)
- data/cmr/cmr_resumen.json
- data/cmr/processed_cmr_names.json (set de cmr_name ya procesados — forward-only)
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / 'data' / 'cmr'
OUT_DIR.mkdir(parents=True, exist_ok=True)

SHEET_ID = '1YAGv-9kqrLWo1wGWzmqlisYJk3-Wuo5r4JmFWUazAiM'
TAB = 'CMR'
CREDENTIALS = PROJECT_ROOT / 'credentials.json'

CUTOFF_FECHA = '2026-04-01'

DRY_RUN = os.environ.get('DRY_RUN', '1') == '1'

URL = os.environ.get('LIBSQL_URL', '').rstrip('/')
TOKEN = os.environ.get('LIBSQL_AUTH_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'}


def _q(sql: str, args: list = None, retries: int = 3):
    stmt = {'sql': sql}
    if args is not None:
        stmt['args'] = args
    body = {'requests': [{'type': 'execute', 'stmt': stmt}, {'type': 'close'}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f'{URL}/v2/pipeline', json=body, headers=HEADERS, timeout=120)
            r.raise_for_status()
            res = r.json()['results'][0]
            if res.get('type') == 'error':
                raise RuntimeError(res['error']['message'])
            return res['response']['result']
        except (requests.exceptions.RequestException, RuntimeError) as e:
            last = e
            time.sleep(2 ** i)
    raise last


def _v(row, idx):
    cell = row[idx]
    return None if cell.get('type') == 'null' else cell.get('value')


def _parse_num_cl(s):
    """Parsea numero formato Chile '89.990' -> 89990 o '15%' -> 0.15."""
    if s is None or s == '' or pd.isna(s):
        return None
    s = str(s).strip().replace('$', '').replace(' ', '').replace('\xa0', '')
    if not s:
        return None
    is_pct = s.endswith('%')
    s = s.rstrip('%')
    # Si tiene punto Y coma -> punto miles, coma decimal
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    elif s.count('.') == 1 and len(s.split('.')[1]) == 3:
        # '89.990' formato chileno: punto miles
        s = s.replace('.', '')
    try:
        n = float(s)
        return n / 100.0 if is_pct else n
    except ValueError:
        return None


def _parse_fecha_dmy(s):
    if not s or pd.isna(s):
        return None
    s = str(s).strip()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def cargar_cmr_sheet():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly',
               'https://www.googleapis.com/auth/drive.readonly']
    creds = Credentials.from_service_account_file(str(CREDENTIALS), scopes=scopes)
    client = gspread.authorize(creds)

    print(f"[1] Abriendo sheet CMR...", flush=True)
    sh = client.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    rows = ws.get_all_values()
    headers = rows[0]
    df = pd.DataFrame(rows[1:], columns=headers)
    print(f"   {len(df)} filas crudas | columnas: {list(df.columns)}", flush=True)

    # Renombrar (acepta variantes nuevas y viejas del header del Sheet)
    df = df.rename(columns={
        'Name': 'cmr_name',
        'SKU': 'sku',
        'Discount Code': 'discount_code',
        'Fecha': 'fecha_raw',
        'Mes': 'mes',
        'Set cupon': 'cupon',
        'Cantidad': 'cantidad_raw',
        'Venta CMR Bruto': 'venta_bruta_raw',
        'Venta CMR Neto': 'venta_neta_raw',
        # Variantes del header de pago (nombres cambiaron en jun-2026)
        'Pago CMR': 'pago_cmr_raw',
        'Pago CMR Neto': 'pago_cmr_raw',
        'Comisión CMR': 'comision_raw',
        'Comisión CMR Neto': 'comision_raw',
        'Comisión %': 'comision_pct_raw',
        'Envío CMR': 'envio_raw',
    })
    # Defensivo: si alguna col esperada falta, créala vacía para evitar KeyError
    for c in ('cmr_name','sku','fecha_raw','cantidad_raw','venta_bruta_raw',
              'venta_neta_raw','pago_cmr_raw','comision_raw','comision_pct_raw','envio_raw'):
        if c not in df.columns:
            df[c] = ''

    df['fecha'] = df['fecha_raw'].apply(_parse_fecha_dmy)
    df['cantidad'] = df['cantidad_raw'].apply(_parse_num_cl)
    df['venta_bruta'] = df['venta_bruta_raw'].apply(_parse_num_cl)
    df['venta_neta'] = df['venta_neta_raw'].apply(_parse_num_cl)
    df['pago_cmr'] = df['pago_cmr_raw'].apply(_parse_num_cl)
    df['comision'] = df['comision_raw'].apply(_parse_num_cl)
    df['comision_pct'] = df['comision_pct_raw'].apply(_parse_num_cl)
    df['envio_cmr'] = df['envio_raw'].apply(_parse_num_cl)

    df = df[df['fecha'].notna() & df['sku'].notna() & (df['cantidad'] > 0)]
    df = df[df['fecha'] >= datetime.strptime(CUTOFF_FECHA, '%Y-%m-%d').date()]
    df['sku'] = df['sku'].str.strip()
    df['cmr_name'] = df['cmr_name'].str.strip()
    print(f"   {len(df)} filas validas ≥ {CUTOFF_FECHA}", flush=True)
    return df


def enriquecer_cmr_df(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica el enriquecimiento CMR a un DataFrame de ventas EN MEMORIA (parquet-native).
    Reemplaza el viejo UPDATE a Turso. Idempotente: re-aplica a TODOS los candidatos
    web-bruta=0 del DataFrame en cada corrida (el parquet se regenera de Odoo cada vez).

    Candidatos: canal IN web AND venta_bruta=0 AND tipo_movimiento='Venta'.
    Match greedy por (fecha_venta, sku) contra el Google Sheet CMR.
    """
    if df is None or df.empty:
        return df
    if not CREDENTIALS.exists():
        print("   [CMR] credentials.json no existe — se omite enriquecimiento CMR", flush=True)
        return df
    try:
        df_cmr = cargar_cmr_sheet()
    except Exception as e:
        print(f"   [CMR] no se pudo leer el sheet ({type(e).__name__}: {str(e)[:80]}) — se omite", flush=True)
        return df
    if df_cmr.empty:
        print("   [CMR] sheet sin filas válidas — se omite", flush=True)
        return df

    df = df.copy()
    fv = pd.to_datetime(df['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    vb = pd.to_numeric(df['venta_bruta'], errors='coerce').fillna(0)
    web = df['canal'].isin(['UnionX web', 'Shopify', 'Lhotse web', 'Simplit web'])
    tv = (df.get('tipo_movimiento') == 'Venta')
    cand_mask = web & (vb == 0) & tv

    # Índices de candidatos. Llave PRIMARIA robusta: (pedido_marketplace, sku) — el
    # 'Name' (#20xxx) del Sheet CMR == pedido_marketplace del pedido web espejo, y NO
    # depende de la fecha (que en el Sheet suele venir corrida 1-2 días). Fallback:
    # (fecha, sku) para filas sin pedido_marketplace.
    tiene_pm = 'pedido_marketplace' in df.columns
    cand_ref = defaultdict(list)
    cand_idx = defaultdict(list)
    for i in df.index[cand_mask]:
        sku_i = str(df.at[i, 'sku']).strip()
        cand_idx[(fv[i], sku_i)].append(i)
        if tiene_pm:
            ref = str(df.at[i, 'pedido_marketplace']).strip()
            if ref:
                cand_ref[(ref, sku_i)].append(i)

    def _aplicar(i, cmr):
        costo = float(pd.to_numeric(df.at[i, 'costo_total'], errors='coerce') or 0)
        neta = float(cmr['venta_neta'] or 0); bruta = float(cmr['venta_bruta'] or 0)
        df.at[i, 'canal'] = 'CMR'; df.at[i, 'tipo_negocio'] = 'Fidelización'
        df.at[i, 'venta_bruta'] = bruta; df.at[i, 'venta_neta'] = neta
        df.at[i, 'margen_front'] = neta - costo; df.at[i, 'margen_final'] = neta - costo
        df.at[i, 'comision'] = 0; df.at[i, 'comision_pct'] = 0; df.at[i, 'logistica'] = 0
        return bruta

    asignados, n, total, n_ref, n_fs = set(), 0, 0.0, 0, 0
    for _, cmr in df_cmr.iterrows():
        sku = str(cmr['sku']).strip()
        nombre = str(cmr.get('cmr_name', '')).strip()
        cands = [(i, 'ref') for i in cand_ref.get((nombre, sku), []) if i not in asignados]
        if not cands:  # fallback fecha+sku
            cands = [(i, 'fs') for i in cand_idx.get((cmr['fecha'].isoformat(), sku), []) if i not in asignados]
        for i, origen in cands:
            total += _aplicar(i, cmr); asignados.add(i); n += 1
            n_ref += origen == 'ref'; n_fs += origen == 'fs'
            break
    print(f"   [CMR] {n} filas enriquecidas (por ref #: {n_ref}, por fecha+sku: {n_fs}), venta bruta +${total:,.0f}", flush=True)
    return df


def main():
    """Standalone: aplica CMR directo al ventas_mes_actual.parquet (sin Turso)."""
    if not CREDENTIALS.exists():
        print(f"[ERROR] {CREDENTIALS} no existe")
        sys.exit(1)
    mes_parquet = PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet'
    if not mes_parquet.exists():
        print(f"[ERROR] {mes_parquet} no existe")
        sys.exit(1)
    print(f"=== Enriquecer CMR en parquet — {datetime.now()} ===", flush=True)
    df = pd.read_parquet(mes_parquet)
    antes = float(pd.to_numeric(df['venta_bruta'], errors='coerce').fillna(0).sum())
    df = enriquecer_cmr_df(df)
    despues = float(pd.to_numeric(df['venta_bruta'], errors='coerce').fillna(0).sum())
    df.to_parquet(mes_parquet, index=False)
    print(f"[OK] {mes_parquet.name}: venta bruta {antes:,.0f} -> {despues:,.0f} (+{despues-antes:,.0f})", flush=True)


def _main_turso_legacy():
    if not URL or not TOKEN:
        print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN faltan")
        sys.exit(1)
    if not CREDENTIALS.exists():
        print(f"[ERROR] {CREDENTIALS} no existe")
        sys.exit(1)

    print(f"=== Sync CMR ventas — {datetime.now()} ===")
    print(f"   Modo: {'DRY_RUN (sin UPDATE)' if DRY_RUN else 'EJECUCION REAL (UPDATE)'}", flush=True)

    df_cmr = cargar_cmr_sheet()

    # Cargar processed_cmr_names para filtrar a forward-only (no re-procesar lo viejo).
    # Si el archivo no existe (primera corrida), procesa todo.
    processed_path = OUT_DIR / 'processed_cmr_names.json'
    processed_names = set()
    if processed_path.exists():
        try:
            processed_names = set(json.load(open(processed_path, encoding='utf-8')))
            print(f"\n   Procesados previamente: {len(processed_names)} cmr_names (forward-only mode)", flush=True)
        except Exception:
            pass
    df_cmr_nuevos = df_cmr[~df_cmr['cmr_name'].isin(processed_names)].copy()
    print(f"   Filas nuevas a procesar: {len(df_cmr_nuevos)} (de {len(df_cmr)} en sheet)", flush=True)
    if df_cmr_nuevos.empty:
        print(f"\n[OK] Nada nuevo que procesar. Saliendo.")
        return
    df_cmr = df_cmr_nuevos

    # Candidatos: web bruta=0 (CMR no marcadas) + CMR ya existentes (para refresh de margen).
    # venta_bruta=0 es el marker tipico de CMR (pago lo procesa CMR, no la web).
    print(f"\n[2] Cargando candidatos Turso (web bruta=0 + CMR existentes desde {CUTOFF_FECHA})...", flush=True)
    res = _q(f"""
        SELECT rowid, pedido, sku, fecha_venta, canal, venta_bruta, tipo_negocio, documento, costo_total
        FROM ventas
        WHERE (
            (canal IN ('UnionX web', 'Shopify', 'Lhotse web', 'Simplit web') AND venta_bruta = 0)
            OR (canal = 'CMR' AND tipo_negocio = 'Fidelización')
          )
          AND fecha_venta >= '{CUTOFF_FECHA}'
          AND tipo_movimiento = 'Venta'
        ORDER BY fecha_venta, pedido, sku
    """)
    candidatos_rows = res.get('rows', [])
    candidatos = []
    for r in candidatos_rows:
        candidatos.append({
            'rowid': int(_v(r, 0)),
            'pedido': _v(r, 1),
            'sku': _v(r, 2),
            'fecha_venta': _v(r, 3),
            'canal': _v(r, 4),
            'venta_bruta': float(_v(r, 5) or 0),
            'tipo_negocio': _v(r, 6),
            'documento': _v(r, 7),
            'costo_total': float(_v(r, 8) or 0),
        })
    print(f"   {len(candidatos)} candidatos en Turso (web bruta=0 + CMR existentes)", flush=True)

    # Index candidatos por (fecha, sku) -> lista ordenada
    cand_idx = defaultdict(list)
    for c in candidatos:
        key = (c['fecha_venta'], c['sku'])
        cand_idx[key].append(c)

    # Matching greedy: por cada CMR row, asigno primer candidato disponible
    print(f"\n[3] Matching CMR sheet vs Turso candidatos...", flush=True)
    matches = []
    no_match = []
    asignados = set()  # rowids ya usados

    for _, cmr in df_cmr.iterrows():
        fecha = cmr['fecha'].isoformat()
        sku = cmr['sku']
        key = (fecha, sku)
        candidatos_key = cand_idx.get(key, [])
        # Primer no asignado
        chosen = None
        for c in candidatos_key:
            if c['rowid'] not in asignados:
                chosen = c
                break
        if chosen:
            asignados.add(chosen['rowid'])
            matches.append({
                'cmr_name': cmr['cmr_name'],
                'cmr_fecha': fecha,
                'sku': sku,
                'turso_rowid': chosen['rowid'],
                'turso_pedido': chosen['pedido'],
                'turso_canal_actual': chosen['canal'],
                'turso_doc': chosen['documento'],
                'turso_costo_total': chosen['costo_total'],
                'venta_bruta_cmr': cmr['venta_bruta'],
                'venta_neta_cmr': cmr['venta_neta'],
                'comision_cmr': cmr['comision'],
                'comision_pct_cmr': cmr['comision_pct'],
                'envio_cmr': cmr['envio_cmr'],
            })
        else:
            no_match.append({
                'cmr_name': cmr['cmr_name'],
                'cmr_fecha': fecha,
                'sku': sku,
                'razon': 'sin candidato Turso' if not candidatos_key else 'todos candidatos asignados',
            })

    print(f"   Matched: {len(matches)}/{len(df_cmr)}", flush=True)
    print(f"   Sin match: {len(no_match)}", flush=True)

    if no_match:
        print(f"\n[4] Top 10 sin match:", flush=True)
        for nm in no_match[:10]:
            print(f"   {nm['cmr_name']} | {nm['cmr_fecha']} | {nm['sku']} | {nm['razon']}", flush=True)

    # UPDATE Turso si no DRY_RUN
    ok_names = set()
    if matches and not DRY_RUN:
        print(f"\n[5] Ejecutando UPDATE en Turso ({len(matches)} filas)...", flush=True)
        ok_count = 0
        for i, m in enumerate(matches, 1):
            bruta = float(m['venta_bruta_cmr'] or 0)
            neta = float(m['venta_neta_cmr'] or 0)
            costo = float(m.get('turso_costo_total') or 0)
            margen_front = neta - costo
            # margen_final = margen_front - comision - logistica - marketing
            # Como ponemos comision=0, logistica=0, marketing=0 -> margen_final = margen_front
            margen_final = margen_front
            rowid = int(m['turso_rowid'])
            update_sql = (
                f"UPDATE ventas SET "
                f"canal = 'CMR', "
                f"tipo_negocio = 'Fidelización', "
                f"venta_bruta = {bruta}, "
                f"venta_neta = {neta}, "
                f"margen_front = {margen_front}, "
                f"margen_final = {margen_final}, "
                f"comision = 0, "
                f"comision_pct = 0, "
                f"logistica = 0 "
                f"WHERE rowid = {rowid}"
            )
            try:
                _q(update_sql)
                ok_count += 1
                ok_names.add(m['cmr_name'])
            except Exception as e:
                print(f"   [FAIL] {m['cmr_name']}: {str(e)[:80]}", flush=True)
                continue
            if i % 25 == 0:
                print(f"   ... {i}/{len(matches)} UPDATEs aplicados", flush=True)
        print(f"   ✓ UPDATE completado: {ok_count}/{len(matches)} OK", flush=True)

        # Persistir el set de procesados (forward-only mode)
        all_processed = processed_names | ok_names
        with open(processed_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(all_processed), f, indent=2)
        print(f"   Procesados acumulados: {len(all_processed)} cmr_names guardados en {processed_path.name}", flush=True)
    elif matches and DRY_RUN:
        print(f"\n[5] DRY_RUN: NO se ejecuta UPDATE. Set DRY_RUN=0 para aplicar.", flush=True)

    # Persistir auditoria
    df_matches = pd.DataFrame(matches)
    if not df_matches.empty:
        out_p = OUT_DIR / 'cmr_matches.parquet'
        df_matches.to_parquet(out_p, compression='zstd', compression_level=9, index=False)
        print(f"\n[6] {out_p.name}: {len(df_matches):,} filas (auditoria)", flush=True)

    resumen = {
        'generado_en': datetime.now().isoformat(),
        'modo': 'DRY_RUN' if DRY_RUN else 'UPDATE',
        'cmr_filas_sheet': len(df_cmr),
        'matched': len(matches),
        'no_match': len(no_match),
        'sample_no_match': no_match[:20],
        'total_venta_bruta_cmr': float(sum(m['venta_bruta_cmr'] or 0 for m in matches)),
        'total_comision_cmr': float(sum(m['comision_cmr'] or 0 for m in matches)),
    }
    with open(OUT_DIR / 'cmr_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resumen, f, indent=2, default=str)

    print(f"\n[OK] Sync CMR completado")
    print(f"   Venta CMR bruta total: ${resumen['total_venta_bruta_cmr']/1e6:.2f}M")
    print(f"   Comisión CMR total: ${resumen['total_comision_cmr']/1e6:.2f}M")


if __name__ == '__main__':
    main()
