# -*- coding: utf-8 -*-
"""Publica la macro de rentabilidad por canal en un Google Sheet compartido.

ARQUITECTURA — cada pestaña tiene UN dueño, y nadie escribe sobre la del otro:

  1. RAW ventas      -> SOLO el script. Se borra y reescribe entera en cada
                        corrida. Gabriela no la toca.
  2. Carga Gabriela  -> SOLO Gabriela. El script NUNCA escribe acá; a lo más la
                        lee. Se siembra una vez con el esqueleto y después es de
                        ella.
  3. Consolidado     -> una FÓRMULA que apila las dos anteriores. Al ser fórmula
                        se actualiza sola cuando cualquiera de los dos carga, y
                        no hay un tercer proceso que pueda pisar nada.
  4. Instrucciones   -> qué llenar y qué no tocar.

Esa separación es el punto: el script puede correr todos los días sin riesgo de
borrarle el trabajo a Gabriela, porque físicamente escribe en otra pestaña.

El id del sheet queda guardado en data/outputs/_macro_rentabilidad_sheet.json
para que las corridas siguientes actualicen el mismo archivo y no creen uno nuevo.

Uso:
    python macro_rentabilidad_drive.py --desde 2026-05 --hasta 2026-08
    python macro_rentabilidad_drive.py --sembrar-gabriela   # solo la 1a vez
"""
import argparse, json, os, re, sys
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
ESTADO = ROOT / 'data/outputs/_macro_rentabilidad_sheet.json'
TITULO = 'Macro rentabilidad por canal — UnionX'
# Id fijo del sheet compartido con Gabriela. Ver el comentario en _abrir().
SHEET_ID_FIJO = '1re-VnNWZiRmfbifJoOPS_oyyzVHVEnuvQ7645Baq4Ck'
H_RAW, H_GAB, H_CON, H_INS = '1. RAW ventas', '2. Carga Gabriela', '3. Consolidado', '4. Instrucciones'

sys.path.insert(0, str(ROOT))
from macro_rentabilidad_canal import (construir, COLS, CC_GABRIELA,  # noqa: E402
                                      SIGNO, MOD_GABRIELA)

H_BASE, H_DIN, H_PCT = '5. Base dinámica', '6. Rentabilidad', '7. Rentabilidad %'
H_LIQ = '2b. Liquidaciones (automático)'
COLS_BASE = COLS[:-1] + ['Monto', 'Fuente']   # Valor -> + columna Monto con signo

# Nombres de canal de la carga de Gabriela y de las liquidaciones → el del RAW (Andrés 6-oct: "Lhotse Web"
# vs "Lhotse web" partía el canal en dos filas y sus costos no caían en su línea de negocio).
ALIAS_CANAL = {'simplit home': 'Simplit web', 'lhotse': 'Lhotse web', 'unionx web': 'UnionX web',
               'latam pass': 'LATAM Pass', 'bice': 'Banco Bice', 'unionxb2b': 'UnionX B2B',
               'mercado libre 2': 'Mercado Libre'}


def canonizar(canales: pd.Series, ref) -> pd.Series:
    ref_l = {str(c).strip().lower(): c for c in ref}

    def f(c):
        k = str(c).strip()
        k = ALIAS_CANAL.get(k.lower(), k)
        return ref_l.get(k.lower(), k)
    return canales.map(f)


def combinar(gab: pd.DataFrame, liq) -> pd.DataFrame:
    """Costos comerciales que entran a la base. Por canal × mes se usa UNA sola fuente: la carga de Gabriela si cargó
    ese canal ese mes (al menos la mitad de lo que da la lectura de su carpeta), o la lectura automática si no (canal
    o mes que todavía no carga). Las reglas que ella pidió y que no carga (comisión % de LATAM, CMR y El Volcán y la
    provisión del Control Aportes) se suman aparte.

    Antes se elegía el mayor costo por centro de costo, y cuando ella y la lectura clasificaban distinto un mismo
    costo se contaba dos veces (Walmart sep: "Servicio Fulfillment" en venta en su carga y en envío en la lectura,
    $296.202; Kitchen Center sep $4,2M). Andrés 9-oct."""
    if liq is None or not len(liq):
        return gab
    es_regla = liq['Glosa'].astype(str).str.contains(r'\(regla\)|Aporte comercial \(provisión\)', regex=True)
    regla, carpeta = liq[es_regla], liq[~es_regla]
    k = ['Mes', 'Canal']
    tg = gab.groupby(k)['Valor'].sum() if len(gab) else pd.Series(dtype=float)
    tl = carpeta.groupby(k)['Valor'].sum()
    usa_gab = {key for key, v in tg.items() if v > 0 and v >= 0.5 * tl.get(key, 0)}
    ig = pd.Series([tuple(x) for x in gab[k].values], index=gab.index).isin(usa_gab) if len(gab) else pd.Series(dtype=bool)
    il = pd.Series([tuple(x) for x in carpeta[k].values], index=carpeta.index).isin(usa_gab)
    return pd.concat([gab[ig], carpeta[~il], regla], ignore_index=True)


# "Control Aportes Uniox y Marketing" (raíz de la carpeta de liquidaciones; Andrés 6-oct): pestaña Aportes,
# Retail = canal de venta (en Falabella, Ripley, Paris y Walmart es la TIENDA, no el digital) y la Provisión
# Neta = comisión de venta del mes. Ej.: Duty Travel agosto = $4.459.720.
CANAL_APORTES = {'duty travel': 'Travel Duty', 'abc': 'Abc', 'falabella': 'Falabella tienda', 'paris': 'Paris tienda',
                 'ripley': 'Ripley tienda', 'walmart': 'Walmart tienda'}
# Reglas de comisión de venta de Gabriela (correo 6-oct "Macro Rentabilidad - Reglas"): % sobre la venta de productos.
REGLAS_COMISION = {'LATAM Pass': 0.15, 'CMR': 0.15, 'El Volcan': 0.30}


def _fila_com(mes, canal, glosa, valor, cc='Comisión venta'):
    return {'Año': int(mes[:4]), 'Mes': mes, 'Línea de negocio': '', 'Canal': canal, 'Modalidad': '',
            'Centro de costo': cc, 'Glosa': glosa, 'Valor': round(float(valor)), 'Fuente': 'Liquidación'}


def leer_aportes(drv, meses) -> pd.DataFrame:
    import io
    from googleapiclient.http import MediaIoBaseDownload
    import rentabilidad_reporte_semanal as R
    fs = drv.files().list(q=f"'{R.CARPETA_LIQ}' in parents and name contains 'Control Aportes' and trashed=false",
                          fields='files(id,name,modifiedTime)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
    fs = sorted([f for f in fs if not f['name'].startswith('~$')], key=lambda f: f['modifiedTime'])
    if not fs:
        return pd.DataFrame(columns=COLS)
    b = io.BytesIO()
    dl = MediaIoBaseDownload(b, drv.files().get_media(fileId=fs[-1]['id'], supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    b.seek(0)
    a = pd.read_excel(b, sheet_name='Aportes')
    a = a[a['Año'].notna() & a['Mes'].notna()].copy()
    a['mes'] = a['Año'].astype(int).astype(str) + '-' + a['Mes'].astype(int).map('{:02d}'.format)
    a = a[a['mes'].isin(meses)]
    a['canal'] = a['Retail'].astype(str).str.strip().map(lambda r: CANAL_APORTES.get(r.lower(), r))
    a['v'] = pd.to_numeric(a['Provisión Neta'], errors='coerce').fillna(0)
    g = a.groupby(['mes', 'canal'], as_index=False)['v'].sum()
    return pd.DataFrame([_fila_com(r.mes, r.canal, 'Aporte comercial (provisión)', r.v) for r in g.itertuples() if r.v],
                        columns=COLS)


def reglas_comision(meses) -> pd.DataFrame:
    """Comisión de venta por regla de Gabriela sobre la venta neta de PRODUCTOS (sin las líneas de envío)."""
    import macro_rentabilidad_canal as MC
    v = MC.cargar_raw(min(meses), max(meses))
    v = v[(v['tipo_movimiento'] == 'Venta') & v['canal'].isin(REGLAS_COMISION)]
    if 'es_despacho' in v.columns:
        v = v[~v['es_despacho'].fillna(False).astype(bool)]
    v = v[~v['sku'].astype(str).str.startswith('Delivery')]
    g = v.groupby(['mes', 'canal'], as_index=False)['venta_neta'].sum()
    return pd.DataFrame([_fila_com(r.mes, r.canal, f'Comisión {REGLAS_COMISION[r.canal] * 100:.0f}% (regla)', r.venta_neta * REGLAS_COMISION[r.canal])
                         for r in g.itertuples() if r.venta_neta], columns=COLS)


# Glosas donde manda la carga de Gabriela aunque la lectura dé más (Andrés 9-oct): FBR de agosto, Ripley no facturó
# todo el almacenamiento (ticket abierto); el archivo dice $82.865 y ella carga lo facturado ($48.677).
SOLO_CARGA = {('2026-08', 'Ripley', 'FBR COBRO ALMACENAMIENTO DIARIO')}


def leer_liquidaciones(meses) -> pd.DataFrame:
    """Lee la carpeta de liquidaciones de Gabriela (los meses pedidos) con su receta: una fila por canal ×
    mes × modalidad × centro de costo × glosa, costo positivo (la convención de su carga). Las glosas sin
    regla no entran (las avisa el vigía)."""
    import tempfile
    import rentabilidad_liquidaciones as RL
    import rentabilidad_reporte_semanal as R
    drv, arbol = R.drive_carpeta()
    partes = []
    for m in meses:
        with tempfile.TemporaryDirectory() as td:
            R.bajar_mes(drv, arbol, int(m[5:7]), Path(td))
            d = RL.leer_carpeta(Path(td))
        if len(d):
            d['Mes'] = m
            partes.append(d)
    extras = []
    for nombre, fn in (('aportes', lambda: leer_aportes(drv, meses)), ('reglas de comisión', lambda: reglas_comision(meses))):
        try:
            extras.append(fn())
        except Exception as e:
            print(f'   [WARN] {nombre}: {type(e).__name__}: {e}')
    out = pd.DataFrame(columns=COLS)
    if partes:
        d = pd.concat(partes, ignore_index=True)
        d = d[d['centro_costo'].isin(CC_GABRIELA)]
        d = d[[(m, c, gl) not in SOLO_CARGA for m, c, gl in zip(d['Mes'], d['canal'], d['glosa'])]]
        g = d.groupby(['Mes', 'canal', 'modalidad_liq', 'centro_costo', 'glosa'], as_index=False)['monto_neto'].sum()
        out = pd.DataFrame({'Año': g['Mes'].str[:4].astype(int), 'Mes': g['Mes'], 'Línea de negocio': '',
                            'Canal': g['canal'], 'Modalidad': g['modalidad_liq'].fillna(''),
                            'Centro de costo': g['centro_costo'], 'Glosa': g['glosa'],
                            'Valor': g['monto_neto'].round(0), 'Fuente': 'Liquidación'})
    out = pd.concat([out] + [e for e in extras if len(e)], ignore_index=True)
    return out[out['Valor'] != 0][COLS]


def _num(s):
    """'$1.520.911' -> 1520911 · '($1.538.485)' -> -1538485 · '-' -> 0"""
    s = str(s).strip()
    if s in ('', '-', '$-', '$ -'):
        return 0.0
    neg = s.startswith('(') or s.startswith('-')
    limpio = re.sub(r'[^0-9,]', '', s).replace(',', '.')
    if not limpio:
        return 0.0
    try:
        x = float(limpio)
    except ValueError:
        return 0.0
    return -x if neg else x


def gab_df(vals_gab, fuera=False) -> pd.DataFrame:
    """Filas con valor de la pestaña de Gabriela, normalizadas (centro de costo y modalidad). Solo entran los
    centros comerciales (CC_GABRIELA): otro centro (ej. "Venta comercial" de Paris y ML en sep, 7-oct) se restaba
    como costo y hundía el margen. fuera=True devuelve esas filas, para listarlas en la 2b como no usadas."""
    g = pd.DataFrame(vals_gab[1:], columns=vals_gab[0])
    g = g[g['Valor'].astype(str).str.strip().ne('')].copy()
    g['Valor'] = g['Valor'].map(_num)
    g = g[g['Valor'] != 0]
    g['Mes'] = g['Mes'].astype(str).str[:7]
    g['Centro de costo'] = g['Centro de costo'].str.strip().str.capitalize().replace(
        {'Comisión envio': 'Comisión envío', 'Comision envío': 'Comisión envío'})
    g['Modalidad'] = g['Modalidad'].str.strip().str.lower().map(MOD_GABRIELA).fillna('')
    g['Fuente'] = 'Gabriela'
    ok = g['Centro de costo'].isin(CC_GABRIELA)
    return g[~ok] if fuera else g[ok]


def comerciales(t, vals_gab, liq=None) -> pd.DataFrame:
    """Costos comerciales que entran a la base: carga de Gabriela + lectura de liquidaciones (combinar()),
    con los nombres de canal del RAW."""
    canales = t['Canal'].unique()
    g = gab_df(vals_gab)
    g['Canal'] = canonizar(g['Canal'], canales)
    if liq is not None and len(liq):
        liq = liq.copy()
        liq['Canal'] = canonizar(liq['Canal'], canales)
        liq['Modalidad'] = liq['Modalidad'].where(liq['Modalidad'].isin(set(MOD_GABRIELA.values())), '')
    return combinar(g, liq)


def armar_base(t, vals_gab, liq=None):
    """RAW + costos comerciales (carga de Gabriela o lectura de sus liquidaciones, ver combinar()), con el
    monto ya con signo y la modalidad resuelta.

    Gabriela carga a nivel canal cuando el marketplace no le informa modalidad.
    Esas filas se prorratean entre las modalidades del canal según su venta neta
    del mes: es el único repartidor que tenemos, y queda declarado acá para que
    nadie lo lea como un dato informado.
    """
    g = comerciales(t, vals_gab, liq)
    g['Línea de negocio'] = g['Línea de negocio'].replace('', pd.NA)

    vent = t[t['Centro de costo'] == 'Ingreso venta']
    peso = vent.groupby(['Año', 'Mes', 'Canal', 'Línea de negocio', 'Modalidad'],
                        as_index=False)['Valor'].sum()
    peso = peso[peso['Valor'] > 0]
    peso['w'] = peso['Valor'] / peso.groupby(['Mes', 'Canal'])['Valor'].transform('sum')

    con = g[g['Modalidad'] != ''].copy()
    sin = g[g['Modalidad'] == ''].copy()
    if len(sin):
        sin = sin.drop(columns=['Modalidad', 'Línea de negocio', 'Año']).merge(
            peso[['Año', 'Mes', 'Canal', 'Línea de negocio', 'Modalidad', 'w']],
            on=['Mes', 'Canal'], how='left')
        huerf = sin['w'].isna()
        if huerf.any():
            print(f'[base] {huerf.sum()} filas de costos sin venta que las reciba '
                  f'(${sin[huerf]["Valor"].sum():,.0f}) — quedan a nivel canal')
            sin.loc[huerf, ['Modalidad', 'w']] = ['Sin modalidad', 1.0]
            sin.loc[huerf, 'Línea de negocio'] = sin.loc[huerf, 'Línea de negocio'].fillna('Sin clasificar')
        sin['Valor'] = sin['Valor'] * sin['w']
        sin = sin.drop(columns=['w'])
    if len(con):
        ln = vent.groupby('Canal')['Línea de negocio'].agg(lambda s: s.mode().iat[0]).to_dict()
        con['Línea de negocio'] = con['Canal'].map(ln).fillna(con['Línea de negocio']).fillna('Sin clasificar')
    gab = pd.concat([x for x in (con, sin) if len(x)], ignore_index=True) if (len(con) or len(sin)) else pd.DataFrame(columns=COLS)
    if len(gab):
        gab['Año'] = gab['Mes'].str[:4].astype(int)
        gab['Fuente'] = gab['Fuente'].fillna('Gabriela')      # 'Gabriela' o 'Liquidación'
        gab = gab[COLS]

    base = pd.concat([t, gab], ignore_index=True) if len(gab) else t.copy()
    base['Monto'] = base['Valor'] * base['Centro de costo'].map(SIGNO).fillna(-1)
    base = base[COLS_BASE]
    return base.sort_values(['Mes', 'Línea de negocio', 'Canal', 'Modalidad', 'Centro de costo'])


def poner_dinamica(sh, ws_base, n_filas):
    """Tabla dinámica NATIVA sobre la base: filas LN/Canal/Modalidad/Centro de
    costo, columnas Mes, valor la suma del Monto (que ya trae el signo)."""
    try:
        wd = sh.worksheet(H_DIN)
        sh.del_worksheet(wd)          # la dinámica se rehace entera
    except gspread.WorksheetNotFound:
        pass
    wd = sh.add_worksheet(title=H_DIN, rows=400, cols=26)
    off = {c: i for i, c in enumerate(COLS_BASE)}
    sh.batch_update({'requests': [{'updateCells': {
        'rows': [{'values': [{'pivotTable': {
            'source': {'sheetId': ws_base.id, 'startRowIndex': 0, 'startColumnIndex': 0,
                       'endRowIndex': n_filas + 1, 'endColumnIndex': len(COLS_BASE)},
            'rows': [{'sourceColumnOffset': off[c], 'showTotals': True,
                      'sortOrder': 'ASCENDING'}
                     for c in ['Línea de negocio', 'Canal', 'Modalidad', 'Centro de costo']],
            'columns': [{'sourceColumnOffset': off['Mes'], 'showTotals': False,
                         'sortOrder': 'ASCENDING'}],
            'values': [{'summarizeFunction': 'SUM', 'sourceColumnOffset': off['Monto'],
                        'name': 'Margen'}],
            'valueLayout': 'HORIZONTAL'}}]}],
        'start': {'sheetId': wd.id, 'rowIndex': 0, 'columnIndex': 0},
        'fields': 'pivotTable'}}]})
    return wd


def poner_vista_pct(sh, base):
    """Vista en % sobre el ingreso: es la que permite comparar canales de tamaño
    distinto. Una dinámica nativa no puede hacerla (Sheets solo sabe % del total
    de fila/columna, no % de una línea concreta), así que se renderiza acá y se
    rehace en cada corrida.

    Tres bloques con el mismo formato: línea de negocio, canal, y canal por
    modalidad. La última columna es la variación del margen en puntos
    porcentuales entre los dos últimos meses, que es lo que dispara la pregunta.
    """
    meses = sorted(base['Mes'].unique())
    ING = 'Ingreso venta'
    COM = ['Comisión venta', 'Comisión envío', 'Marketing']

    def bloque(dims, titulo):
        filas = [[titulo] + [''] * (len(dims) - 1 + 5 * len(meses) + 1)]
        enc = list(dims)
        for m in meses:
            enc += [f'{m} Ingreso', f'{m} % Devol', f'{m} % Costo', f'{m} % Com+Mkt', f'{m} % Margen']
        enc += ['Δ margen p.p.']
        filas.append(enc)
        g = base.groupby(dims + ['Mes', 'Centro de costo'], as_index=False)['Monto'].sum()
        # Cada celda es una FÓRMULA sobre '5. Base dinámica' (pedido Andrés 28-09: que se
        # vea cómo se construye). Monto = col I, Mes = B, LN = C, Canal = D, Modalidad = E,
        # Centro = F. Locale es_ES → separador ';'. El orden de filas sí lo fija el script.
        B = f"'{H_BASE}'!"
        dimcol = {'Línea de negocio': 'C', 'Canal': 'D', 'Modalidad': 'E'}
        cuerpo = []
        for clave, sub in g.groupby(dims):
            clave = clave if isinstance(clave, tuple) else (clave,)
            orden = float(sub[(sub['Mes'] == meses[-1]) & (sub['Centro de costo'] == ING)]['Monto'].sum()) if meses else 0
            cuerpo.append((orden, clave))
        cuerpo.sort(key=lambda t: t[0], reverse=True)
        out = []
        for _, clave in cuerpo:
            r = len(filas) + len(out) + 1 + fila0[0]          # fila en la hoja (1-based)
            crit = ';'.join(f'{B}${dimcol[d]}:${dimcol[d]};"{str(v).replace(chr(34), "")}"' for d, v in zip(dims, clave))
            fila = list(clave)
            refs = []
            for k, m in enumerate(meses):
                c0 = len(dims) + 5 * k + 1                      # columna del Ingreso del mes (1-based)
                ci = col(c0)
                sm = lambda cc: f'SUMIFS({B}$I:$I;{crit};{B}$B:$B;"{m}";{B}$F:$F;"{cc}")'  # noqa: E731
                ing = f'={sm(ING)}'
                pdev = f'=IFERROR({sm("Devolución")}/{ci}{r};"")'
                pcos = f'=IFERROR(({sm("Costo venta")}+{sm("Otros costos")})/{ci}{r};"")'
                pcom = f'=IFERROR(({"+".join(sm(c) for c in COM)})/{ci}{r};"")'
                pmg = f'=IFERROR(SUMIFS({B}$I:$I;{crit};{B}$B:$B;"{m}")/{ci}{r};"")'
                fila += [ing, pdev, pcos, pcom, pmg]
                refs.append(f'{col(c0 + 4)}{r}')
            fila.append(f'=IFERROR({refs[-1]}-{refs[-2]};"")' if len(refs) > 1 else '')
            out.append(fila)
        return filas + out + [[''] * len(enc)]

    col = lambda i: chr(64 + i) if i <= 26 else chr(64 + (i - 1) // 26) + chr(65 + (i - 1) % 26)  # noqa: E731
    todo, bloques = [], []
    fila0 = [0]
    for dims, titulo in [(['Línea de negocio'], 'POR LÍNEA DE NEGOCIO'),
                         (['Canal'], 'POR CANAL'),
                         (['Canal', 'Modalidad'], 'POR CANAL Y MODALIDAD')]:
        fila0[0] = len(todo)
        f = bloque(dims, titulo)
        bloques.append({'ini': len(todo) + 1, 'fin': len(todo) + len(f), 'nd': len(dims)})
        todo += f
    ancho = max(len(r) for r in todo)
    todo = [r + [''] * (ancho - len(r)) for r in todo]

    ws = _hoja(sh, H_PCT, filas=max(len(todo) + 20, 300), cols=max(ancho + 2, 26))
    ws.clear()
    ws.update(todo, value_input_option='USER_ENTERED')
    ws.freeze(rows=2, cols=2)

    az = {'red': .118, 'green': .227, 'blue': .373}
    blanco = {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
    pesos = {'numberFormat': {'type': 'CURRENCY', 'pattern': '$#,##0'}}
    pct = {'numberFormat': {'type': 'PERCENT', 'pattern': '0.0%'}}

    for b in bloques:
        ini, fin, nd = b['ini'], b['fin'], b['nd']
        ws.format(f'A{ini}:{col(ancho)}{ini}', {'textFormat': blanco, 'backgroundColor': az})
        ws.format(f'A{ini + 1}:{col(ancho)}{ini + 1}',
                  {'textFormat': {'bold': True}, 'wrapStrategy': 'WRAP',
                   'backgroundColor': {'red': .922, 'green': .941, 'blue': .973}})
        datos_ini, datos_fin = ini + 2, fin
        if datos_fin < datos_ini:
            continue
        for k in range(len(meses)):
            c_ing = nd + 5 * k + 1                    # Ingreso del mes k
            ws.format(f'{col(c_ing)}{datos_ini}:{col(c_ing)}{datos_fin}', pesos)
            ws.format(f'{col(c_ing + 1)}{datos_ini}:{col(c_ing + 4)}{datos_fin}', pct)
        c_delta = nd + 5 * len(meses) + 1             # Δ margen, en puntos porcentuales
        ws.format(f'{col(c_delta)}{datos_ini}:{col(c_delta)}{datos_fin}', pct)
    print(f'[{H_PCT}] {len(todo)} filas · 3 bloques')
    return ws


def _cli():
    # En GH Actions no existe el archivo: el token viene en el secret
    # DRIVE_OAUTH_TOKEN_JSON, igual que en el resto de los procesos de Drive.
    env = os.environ.get('DRIVE_OAUTH_TOKEN_JSON', '').strip()
    if env:
        creds = Credentials.from_authorized_user_info(json.loads(env))
    else:
        creds = Credentials.from_authorized_user_file(str(ROOT / 'drive_oauth_token.json'))
    if not creds.valid:
        creds.refresh(Request())
    return gspread.authorize(creds)


def _abrir(gc, crear_si_falta=True):
    # OJO: data/outputs/ está en .gitignore, así que en GH Actions el archivo de
    # estado NO existe. Sin este fallback el proceso crearía un sheet nuevo cada
    # lunes y Gabriela seguiría cargando en el viejo. El id va fijo por eso.
    sid = os.environ.get('MACRO_SHEET_ID', '').strip() or SHEET_ID_FIJO
    if ESTADO.exists():
        sid = json.load(open(ESTADO)).get('sheet_id') or sid
    if sid:
        try:
            return gc.open_by_key(sid), False
        except Exception:
            print(f'[WARN] no se pudo abrir el sheet {sid}')
    if not crear_si_falta:
        sys.exit('[ERROR] no hay sheet creado todavía')
    sh = gc.create(TITULO)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps({'sheet_id': sh.id, 'url': sh.url}, indent=1), encoding='utf-8')
    print(f'[nuevo] {sh.url}')
    return sh, True


def _hoja(sh, nombre, filas=1000, cols=12):
    try:
        return sh.worksheet(nombre)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=nombre, rows=filas, cols=cols)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--desde', default='2026-05')
    ap.add_argument('--hasta', default='2026-08')
    ap.add_argument('--sembrar-gabriela', action='store_true',
                    help='siembra el esqueleto en la pestaña de Gabriela (solo la 1a vez)')
    a = ap.parse_args()

    t, _ = construir(a.desde, a.hasta)
    gc = _cli()
    sh, nuevo = _abrir(gc)

    # ---- 1. RAW ventas: propiedad exclusiva del script ----
    ws = _hoja(sh, H_RAW, filas=max(len(t) + 50, 500))
    ws.clear()
    ws.update([COLS] + t.astype(object).where(pd.notna(t), '').values.tolist(),
              value_input_option='RAW')
    ws.freeze(rows=1)
    ws.format('A1:I1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                        'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
    print(f'[{H_RAW}] {len(t)} filas escritas')

    # ---- 2. Carga Gabriela: NUNCA se sobrescribe ----
    wg = _hoja(sh, H_GAB, filas=3000)
    vals = wg.get_all_values()
    if a.sembrar_gabriela or len(vals) <= 1:
        base = t[['Año', 'Mes', 'Línea de negocio', 'Canal']].drop_duplicates()
        pl = base.merge(pd.DataFrame({'Centro de costo': CC_GABRIELA}), how='cross')
        pl['Modalidad'] = ''; pl['Glosa'] = ''; pl['Valor'] = ''; pl['Fuente'] = 'Gabriela'
        pl = pl[COLS]
        wg.clear()
        wg.update([COLS] + pl.astype(object).values.tolist(), value_input_option='RAW')
        wg.freeze(rows=1)
        wg.format('A1:I1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                            'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
        print(f'[{H_GAB}] sembrado con {len(pl)} filas — de aquí en adelante es de ella')
    else:
        llenas = sum(1 for r in vals[1:] if len(r) > 7 and str(r[7]).strip())
        print(f'[{H_GAB}] INTACTA — {len(vals)-1} filas, {llenas} con valor cargado')

    # ---- 3. Consolidado: fórmula, se actualiza solo ----
    wc = _hoja(sh, H_CON, filas=200, cols=12)
    wc.clear()
    wc.update([COLS], value_input_option='RAW')
    # QUERY y no FILTER: apila las dos pestañas y descarta las filas sin Valor
    # (las que Gabriela todavía no llena).
    # OJO: el sheet está en locale es_ES, donde el separador de argumentos es
    # PUNTO Y COMA. Con coma da #ERROR!. El ; también separa filas del array {}.
    wc.update_acell('A2',
                    f"=QUERY({{'{H_RAW}'!A2:I; '{H_GAB}'!A2:I}}; "
                    f'"select * where Col8 is not null"; 0)')
    wc.freeze(rows=1)
    wc.format('A1:I1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                        'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
    print(f'[{H_CON}] fórmula puesta (apila las dos pestañas, se actualiza sola)')

    # ---- 5. Base para la dinámica ----
    # Tabla plana con el MONTO YA CON SIGNO, y con los costos de Gabriela
    # bajados a modalidad. Con el signo aplicado, el total de la dinámica es
    # directamente el margen: no hace falta campo calculado y al filtrar sigue
    # cuadrando con lo filtrado.
    # ---- 2b. Liquidaciones (automático): lectura de la carpeta de Gabriela con su receta ----
    vals_gab = wg.get_all_values()
    liq = None
    try:
        liq = leer_liquidaciones(sorted(t['Mes'].astype(str).str[:7].unique()))
        liq['Canal'] = canonizar(liq['Canal'], t['Canal'].unique())
        usadas = comerciales(t, vals_gab, liq)
        claves = set(map(tuple, usadas.loc[usadas['Fuente'] == 'Liquidación', ['Mes', 'Canal', 'Centro de costo']].values))
        vista = liq.copy()
        vista['Usada en la base'] = ['Sí' if (m, c, cc) in claves else 'No (manda la carga de Gabriela)'
                                     for m, c, cc in zip(vista['Mes'], vista['Canal'], vista['Centro de costo'])]
        fuera = gab_df(vals_gab, fuera=True)
        if len(fuera):
            fuera = fuera.reindex(columns=COLS).assign(**{'Usada en la base': 'No (centro de costo no comercial, de la carga de Gabriela)'})
            vista = pd.concat([vista, fuera], ignore_index=True)
            print(f'[{H_LIQ}] {len(fuera)} filas de la carga de Gabriela fuera de {CC_GABRIELA}: no entran al margen')
        wl = _hoja(sh, H_LIQ, filas=max(len(vista) + 50, 300), cols=11)
        wl.clear()
        wl.update([list(vista.columns)] + vista.astype(object).values.tolist(), value_input_option='RAW')
        wl.freeze(rows=1)
        wl.format('A1:J1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                            'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
        print(f'[{H_LIQ}] {len(vista)} filas · ${liq["Valor"].sum():,.0f} · usadas {len(claves)} canal×mes×centro')
    except Exception as e:      # sin acceso a la carpeta: la base sale solo con la carga de Gabriela
        print(f'[{H_LIQ}] [WARN] no se pudieron leer las liquidaciones: {type(e).__name__}: {e}')
        liq = None

    base = armar_base(t, vals_gab, liq)
    wb_ = _hoja(sh, H_BASE, filas=max(len(base) + 50, 500), cols=11)
    wb_.clear()
    wb_.update([COLS_BASE] + base.astype(object).where(pd.notna(base), '').values.tolist(),
               value_input_option='RAW')
    wb_.freeze(rows=1)
    wb_.format('A1:J1', {'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                         'backgroundColor': {'red': .118, 'green': .227, 'blue': .373}})
    print(f'[{H_BASE}] {len(base)} filas · margen total ${base["Monto"].sum():,.0f}')

    # ---- 6. Rentabilidad: tabla dinámica NATIVA ----
    poner_dinamica(sh, wb_, len(base))
    print(f'[{H_DIN}] dinámica nativa apuntando a {H_BASE}')

    # ---- 7. Rentabilidad %: la vista que permite comparar canales distintos ----
    poner_vista_pct(sh, base)

    # ---- 4. Instrucciones ----
    wi = _hoja(sh, H_INS, filas=60, cols=2)
    wi.clear()
    ins = [
        ['MACRO DE RENTABILIDAD POR CANAL', ''],
        ['', ''],
        ['CÓMO FUNCIONA', ''],
        ['Cada pestaña tiene un dueño. Nadie escribe sobre la del otro.', ''],
        ['', ''],
        [f'{H_RAW}', 'La escribe el proceso automático desde el RAW de ventas. Trae Ingreso venta '
                     'y Costo venta. NO editar: se borra y reescribe entera en cada corrida.'],
        [f'{H_GAB}', 'Es tuya, Gabriela. El proceso automático nunca escribe acá. Carga Comisión '
                     'venta, Comisión envío y Marketing. Otro centro de costo no entra al margen: se lista en la 2b '
                     'como no usado.'],
        [f'{H_CON}', 'Se arma sola con una fórmula que apila las dos anteriores. No editar.'],
        [f'{H_LIQ}', 'La escribe el proceso automático: lectura de las liquidaciones de la carpeta de Drive con la '
                     'receta de glosas (marketplaces, couriers, Kitchen Center, Bice). No editar.'],
        ['5. Base dinámica', 'RAW + costos comerciales. Por canal y mes entra una sola fuente: tu carga si '
                             'cargaste ese canal ese mes, o la lectura de tus liquidaciones si no. Las reglas de comisión '
                             '(LATAM, CMR, El Volcán) y el Control Aportes se suman aparte. La columna Fuente dice cuál se usó.'],
        ['', ''],
        ['QUÉ LLENAR EN TU PESTAÑA', ''],
        ['Glosa', 'La glosa contable que corresponda. Son siempre las mismas y se repiten mes a mes.'],
        ['Valor', 'El monto. Es lo único obligatorio: una fila sin Valor no entra al consolidado.'],
        ['Modalidad', 'Opcional. Si el costo aplica a todo el canal sin distinguir modalidad '
                      'logística, déjalo en blanco.'],
        ['', ''],
        ['Puedes agregar filas al final si necesitas una glosa que no está prellenada.', ''],
        ['Lo único que importa es respetar las columnas.', ''],
        ['', ''],
        ['EL MARGEN NO SE CARGA', ''],
        ['Es una resta de las otras filas. Si se guardara como dato, al filtrar la tabla dinámica '
         'dejaría de cuadrar con lo filtrado. Va como campo calculado en la dinámica.', ''],
        ['', ''],
        ['MODALIDAD LOGÍSTICA — qué significa cada una', ''],
        ['Fulfillment', 'El marketplace almacena y despacha (ML Full, FBF de Falabella, WFS).'],
        ['Colecta', 'El stock es nuestro y el marketplace lo retira y despacha. Incluye los puntos de '
                    'entrega (drop-off de Meli, retiro en tienda de Ripley).'],
        ['Envío directo', 'Despachamos nosotros al cliente (Flex, envío directo, tiendas propias).'],
        ['Consignación', 'El Volcán: retiene 30% de comisión.'],
        ['Venta directa', 'B2B, distribución y corporativo: sin modalidad de marketplace.'],
    ]
    wi.update(ins, value_input_option='RAW')
    wi.format('A1', {'textFormat': {'bold': True, 'fontSize': 13}})
    wi.columns_auto_resize(0, 1)
    print(f'[{H_INS}] listo')

    try:
        sh.del_worksheet(sh.worksheet('Hoja 1'))
    except Exception:
        pass
    try:
        sh.del_worksheet(sh.worksheet('Sheet1'))
    except Exception:
        pass

    print(f'\n[OK] {sh.url}')


if __name__ == '__main__':
    main()
