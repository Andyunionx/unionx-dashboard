"""Agente NC (Notas de Crédito) — UnionX. Reconstruido 23-jul-2026 (el original fue borrado por sync Drive).

Pipeline:
  1. Lee las 3 planillas SAC (Google Sheets via CSV export + OAuth Bearer):
     P1 Marketplace / P2 Outlet-Merma / P3 Nuevo
  2. Clasifica cada línea: LEGACY (BSALE/FF o año<2026, fuera de análisis por decisión 20-jul),
     EMITIDA (NC con folio), PENDIENTE.
  3. Cruza pendientes contra Odoo: pedido (channel_order_reference / client_order_ref / name,
     con variantes sin '#' y sin sufijo '-A') → NC asociadas (out_refund) y recepción física
     de la devolución (pickings de retorno done → f_recepcion).
  4. Genera: NC_2026_DISPONIBLES_emitir.xlsx (disponibles + pivote canal×mes + detalle)
             NC_2026_por_mes_canal_estado.xlsx (resumen mes/canal/estado N-O-M)

REGLA PERMANENTE: este script NUNCA crea NC en Odoo. Solo lectura + reportes.
USO: python agente_nc.py            # regenera reportes
     (sin flags de envío: los mails se redactan aparte, con OK de Andrés)
"""
import sys, io, re, os, json
sys.stdout.reconfigure(encoding='utf-8')
import requests
import pandas as pd
from collections import defaultdict
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import xmlrpc.client

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.path.join(BASE, 'agente-comex', 'config', 'token.json')
OUT = os.path.join(BASE, 'data', 'outputs')

PLANILLAS = {
    'Marketplace': '1sYZx7RcPhhejqedH3omEaF-kAtV48dp2SEjApoHm73E',
    'OutletMerma': '1ylxMk-iL5bBpSXyvjx-ZaPWdqQ6vU2GyKNWe_wc23Co',
    'Nuevo':       '18eJYfaqLlDmLfCpyaD77uDlteBruVy1_UtIM5ahllIk',
}

def sheets_csv(fid, creds):
    r = requests.get(f'https://docs.google.com/spreadsheets/d/{fid}/export?format=csv',
                     headers={'Authorization': f'Bearer {creds.token}'}, timeout=90)
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content), dtype=str)

def monto_abs(s):
    d = re.sub(r'[^0-9]', '', str(s or ''))
    return int(d) if d else 0

def parse_fecha(s):
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try: return pd.to_datetime(str(s).strip(), format=fmt)
        except Exception: pass
    return pd.NaT

def variantes_oc(oc):
    # variantes de referencia: sin '#', sin sufijo '-A', sin sufijo '_N' (splits de
    # ML: '2000011909409603_1'), y combinaciones. Ampliado 14-08 (179 sin mapear).
    oc = str(oc or '').strip()
    if not oc: return []
    base = {oc, oc.lstrip('#')}
    mas = set()
    for x in base:
        mas.add(x.replace('-A', ''))
        mas.add(re.sub(r'_\d+$', '', x))
        mas.add(re.sub(r'_\d+$', '', x.replace('-A', '')))
    v = base | mas | {'#' + x for x in mas if x and not x.startswith('#')}
    return [x for x in v if x]

def main():
    # CI: GMAIL_TOKEN_JSON (mismo secret de los pulsos); local: token.json agente-comex
    cj = os.environ.get('GMAIL_TOKEN_JSON', '')
    if cj:
        creds = Credentials.from_authorized_user_info(json.loads(cj), json.loads(cj).get('scopes'))
    else:
        creds = Credentials.from_authorized_user_file(TOKEN)
    if creds.expired and creds.refresh_token: creds.refresh(Request())

    # ===== 1) CARGA =====
    frames = []
    p1 = sheets_csv(PLANILLAS['Marketplace'], creds)
    p1 = p1.rename(columns=lambda c: str(c).strip())
    f1 = pd.DataFrame({
        'origen': 'Marketplace', 'estado_tipo': 'Marketplace',
        'canal': p1.get('Canal', ''), 'caso': '',
        'oc': p1.get('OC', ''), 'boleta': p1.get('Boleta', ''),
        'sku': p1.get('SKU', ''), 'producto': p1.get('Producto', ''),
        'razon': p1.get('Comentario Maximiliano', ''),
        'nc': p1.get('NC', ''), 'monto': p1.get('Monto a devolver', '').map(monto_abs),
        'fecha': p1.get('Fecha documento', '').map(parse_fecha),
        'estado_sac': p1.get('Estado SAC', ''), 'nc_ingresada': p1.get('NC ingresada', ''),
        'apelada': p1.get('Apelada', ''),
    })
    frames.append(f1)
    for nm in ('OutletMerma', 'Nuevo'):
        p = sheets_csv(PLANILLAS[nm], creds).rename(columns=lambda c: str(c).strip())
        f = pd.DataFrame({
            'origen': nm, 'estado_tipo': p.get('Estado', ''),
            'canal': p.get('Cliente', ''), 'caso': p.get('Caso', ''),
            'oc': p.get('OC', ''), 'boleta': '',
            'sku': p.get('SKU', ''), 'producto': p.get('Producto', ''),
            'razon': p.get('Motivo', '') if 'Motivo' in p.columns else '',
            'nc': p.get('NC', ''), 'monto': 0,
            'cantidad': p.get('Cantidad', '1'),
            'fecha': p.get('Fecha', '').map(parse_fecha),
        })
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    df['oc'] = df['oc'].astype(str).str.strip()
    df = df[df['oc'].ne('') & df['oc'].ne('nan')]
    df['mes'] = df['fecha'].dt.strftime('%Y-%m')
    df['anio'] = df['fecha'].dt.year

    # ===== 2) CLASIFICACION BASE =====
    nc = df['nc'].astype(str).str.strip().str.upper()
    for c in ('estado_sac', 'nc_ingresada', 'apelada'):
        if c not in df.columns: df[c] = ''
        df[c] = df[c].fillna('').astype(str).str.strip()
    df['clase'] = 'PENDIENTE'
    df.loc[nc.isin(['BSALE', 'FF']), 'clase'] = 'LEGACY'
    df.loc[(~nc.isin(['BSALE', 'FF', '', 'NAN', 'NONE'])) & nc.ne(''), 'clase'] = 'EMITIDA'
    df.loc[df['nc_ingresada'].str.lower().isin(['sí', 'si']), 'clase'] = 'EMITIDA'
    df.loc[(df['clase'] == 'PENDIENTE') & df['apelada'].str.lower().isin(['sí', 'si']), 'clase'] = 'APELADA'
    df.loc[(df['clase'] == 'PENDIENTE') & df['estado_sac'].str.startswith('Resuelta'), 'clase'] = 'RESUELTA SAC'
    df.loc[(df['clase'] == 'PENDIENTE') & df['estado_sac'].str.startswith('No ingresada'), 'clase'] = 'SIN RECEPCION (P1)'
    df.loc[df['anio'] < 2026, 'clase'] = df.loc[df['anio'] < 2026, 'clase'].map(
        lambda c: 'LEGACY(<2026 no necesario)' if c == 'PENDIENTE' else c)
    print("Clases:", df['clase'].value_counts().to_dict())

    pend = df[(df['clase'] == 'PENDIENTE') & (df['anio'] >= 2026)].copy()
    print(f"PENDIENTES 2026: {len(pend)} líneas / {pend['oc'].nunique()} OC")

    # ===== 3) CRUCE ODOO =====
    cfg = json.load(open(os.path.join(BASE, 'odoo', 'odoo_config.json')))['produccion']
    pw = os.environ.get('ANDRES_ODOO_PASSWORD', '') or open(os.path.join(BASE, 'odoo', '.odoo_pass')).read().strip()
    uid = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common").authenticate(cfg['db_name'], cfg['username'], pw, {})
    def rpc(model, method, args, kw=None):
        return xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object").execute_kw(
            cfg['db_name'], uid, pw, model, method, args, kw or {})

    todas = sorted({v for oc in pend['oc'].unique() for v in variantes_oc(oc)})
    so_by_ref = {}
    for i in range(0, len(todas), 300):
        ch = todas[i:i+300]
        for f_ in ('channel_order_reference', 'client_order_ref', 'name'):
            try:
                for s in rpc('sale.order', 'search_read', [[(f_, 'in', ch)]],
                             {'fields': ['name', 'client_order_ref', 'channel_order_reference',
                                         'date_order', 'invoice_ids', 'picking_ids']}):
                    for k in ('channel_order_reference', 'client_order_ref', 'name'):
                        val = str(s.get(k) or '').strip()
                        if val: so_by_ref.setdefault(val, s)
            except xmlrpc.client.Fault:
                pass
    print(f"Pedidos Odoo matcheados: {len(so_by_ref)} refs")

    def so_de(oc):
        for v in variantes_oc(oc):
            if v in so_by_ref: return so_by_ref[v]
        return None

    sos = {s['id']: s for s in (so_de(oc) for oc in pend['oc'].unique()) if s}
    inv_ids = sorted({i for s in sos.values() for i in s['invoice_ids']})
    ncs_odoo = {}
    for i in range(0, len(inv_ids), 400):
        for m in rpc('account.move', 'search_read',
                     [[('id', 'in', inv_ids[i:i+400]), ('move_type', '=', 'out_refund'), ('state', '=', 'posted')]],
                     {'fields': ['name', 'invoice_origin', 'date']}):
            ncs_odoo[m['id']] = m
    bel = {}
    for i in range(0, len(inv_ids), 400):
        for m in rpc('account.move', 'search_read',
                     [[('id', 'in', inv_ids[i:i+400]), ('move_type', '=', 'out_invoice')]],
                     {'fields': ['name', 'invoice_origin']}):
            bel[m['id']] = m['name']
    pk_ids = sorted({p for s in sos.values() for p in s['picking_ids']})
    rets = defaultdict(list)
    for i in range(0, len(pk_ids), 400):
        for p in rpc('stock.picking', 'search_read',
                     [[('id', 'in', pk_ids[i:i+400]), ('state', '=', 'done'),
                       ('picking_type_id.code', '=', 'incoming')]],
                     {'fields': ['name', 'date_done', 'sale_id']}):
            if p['sale_id']: rets[p['sale_id'][0]].append(p['date_done'][:10])

    def enrich(oc):
        s = so_de(oc)
        if not s: return pd.Series({'pedido': '', 'boleta_odoo': '', 'fecha_compra': '',
                                    'nc_odoo': '', 'f_recepcion': ''})
        ncs = [ncs_odoo[i]['name'] for i in s['invoice_ids'] if i in ncs_odoo]
        bels = [bel[i] for i in s['invoice_ids'] if i in bel]
        r = sorted(rets.get(s['id'], []))
        return pd.Series({'pedido': s['name'], 'boleta_odoo': bels[0] if bels else '',
                          'fecha_compra': str(s['date_order'])[:10],
                          'nc_odoo': ', '.join(ncs), 'f_recepcion': r[0] if r else ''})

    info = {oc: enrich(oc) for oc in pend['oc'].unique()}
    for col in ('pedido', 'boleta_odoo', 'fecha_compra', 'nc_odoo', 'f_recepcion'):
        pend[col] = pend['oc'].map(lambda o: info[o][col])
    pend['boleta'] = pend['boleta'].where(pend['boleta'].astype(str).str.strip().ne(''), pend['boleta_odoo'])
    pend.loc[pend['nc_odoo'].ne(''), 'clase'] = 'CON NC EN ODOO'
    es_fisica = pend['origen'].isin(['OutletMerma', 'Nuevo'])
    pend.loc[(pend['clase'] == 'PENDIENTE') & es_fisica, 'clase'] = 'DISPONIBLE'
    pend.loc[(pend['clase'] == 'PENDIENTE') & pend['f_recepcion'].ne(''), 'clase'] = 'DISPONIBLE'
    pend.loc[pend['clase'] == 'PENDIENTE', 'clase'] = 'SIN RECEPCION'
    # f_recepcion para P2/P3 = fecha de clasificacion en bodega (la planilla se llena al llegar)
    m = es_fisica & pend['f_recepcion'].eq('')
    pend.loc[m, 'f_recepcion'] = pend.loc[m, 'fecha'].dt.strftime('%Y-%m-%d')
    # montos P2/P3: precio de la linea del pedido en Odoo (producto devuelto)
    need = pend[es_fisica & pend['monto'].eq(0) & pend['pedido'].ne('')]
    so_ids = {so_by_ref[v]['id']: v for oc in need['oc'].unique() for v in variantes_oc(oc) if v in so_by_ref}
    lines_by_so = defaultdict(dict)
    sids = list(so_ids)
    for i in range(0, len(sids), 200):
        for l in rpc('sale.order.line', 'search_read', [[('order_id', 'in', sids[i:i+200])]],
                     {'fields': ['order_id', 'product_id', 'price_total', 'product_uom_qty']}):
            code = str(l['product_id'][1]).split(']')[0].lstrip('[') if l['product_id'] and '[' in str(l['product_id'][1]) else ''
            if code and l['product_uom_qty']:
                lines_by_so[l['order_id'][0]][code] = l['price_total'] / l['product_uom_qty']
    def monto_linea(row):
        if row['monto']: return row['monto']
        s = so_de(row['oc'])
        if not s: return 0
        unit = lines_by_so.get(s['id'], {}).get(str(row['sku']).strip(), 0)
        try: qty = float(str(row.get('cantidad') or '1').replace(',', '.'))
        except Exception: qty = 1
        return round(unit * qty)
    pend['monto'] = pend.apply(monto_linea, axis=1)
    print("\nEstados pendientes 2026:", pend['clase'].value_counts().to_dict())

    # ===== 4) SALIDAS =====
    disp = pend[pend['clase'] == 'DISPONIBLE'].copy()
    disp['razon'] = disp['razon'].fillna('').replace('', '(sin razón)').fillna('(sin razón)')
    g = disp.groupby('oc').agg(caso=('caso', 'first'), canal=('canal', 'first'), mes=('mes', 'first'),
                               boleta=('boleta', 'first'), pedido=('pedido', 'first'),
                               fecha_compra=('fecha_compra', 'first'), f_recepcion=('f_recepcion', 'first'),
                               razon=('razon', 'first'), n_lineas=('sku', 'size'),
                               monto_NC=('monto', 'sum')).reset_index().sort_values('monto_NC', ascending=False)
    piv = disp.pivot_table(index='mes', columns='canal', values='monto', aggfunc='sum', fill_value=0, margins=True, margins_name='All')
    with pd.ExcelWriter(os.path.join(OUT, 'NC_2026_DISPONIBLES_emitir.xlsx')) as w:
        g.to_excel(w, sheet_name=f'{len(g)} NC a emitir', index=False)
        piv.to_excel(w, sheet_name='Pivote canal x mes')
        disp[['fecha', 'mes', 'canal', 'estado_tipo', 'oc', 'caso', 'boleta', 'sku', 'razon',
              'fecha_compra', 'f_recepcion', 'monto']].to_excel(w, sheet_name=f'Detalle {len(disp)} lineas', index=False)
    res = pend.pivot_table(index='mes', columns='clase', values='oc', aggfunc='nunique', fill_value=0)
    resm = pend.pivot_table(index=['mes', 'canal'], columns='clase', values='monto', aggfunc='sum', fill_value=0)
    tipo = df[df['anio'] >= 2026].pivot_table(index='mes', columns='estado_tipo', values='oc', aggfunc='nunique', fill_value=0)
    with pd.ExcelWriter(os.path.join(OUT, 'NC_2026_por_mes_canal_estado.xlsx')) as w:
        res.to_excel(w, sheet_name='OC por mes x estado')
        resm.to_excel(w, sheet_name='Monto mes-canal x estado')
        tipo.to_excel(w, sheet_name='Relacion Nuevo-Outlet-Merma')
    print(f"\nDISPONIBLES: {len(g)} OC | ${g['monto_NC'].sum():,.0f} (montos solo marketplace)")
    print(f"SIN RECEPCION: {pend[pend['clase']=='SIN RECEPCION']['oc'].nunique()} OC | ${pend[pend['clase']=='SIN RECEPCION']['monto'].sum():,.0f}")
    print(f"CON NC EN ODOO (ya resueltas): {pend[pend['clase']=='CON NC EN ODOO']['oc'].nunique()} OC")
    print("Archivos regenerados en data/outputs/")

if __name__ == '__main__':
    main()
