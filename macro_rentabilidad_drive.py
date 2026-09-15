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

H_BASE, H_DIN = '5. Base dinámica', '6. Rentabilidad'
COLS_BASE = COLS[:-1] + ['Monto', 'Fuente']   # Valor -> + columna Monto con signo


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


def armar_base(t, vals_gab):
    """RAW + carga de Gabriela, con el monto ya con signo y la modalidad resuelta.

    Gabriela carga a nivel canal cuando el marketplace no le informa modalidad.
    Esas filas se prorratean entre las modalidades del canal según su venta neta
    del mes: es el único repartidor que tenemos, y queda declarado acá para que
    nadie lo lea como un dato informado.
    """
    g = pd.DataFrame(vals_gab[1:], columns=vals_gab[0])
    g = g[g['Valor'].astype(str).str.strip().ne('')].copy()
    g['Valor'] = g['Valor'].map(_num)
    g = g[g['Valor'] != 0]
    g['Centro de costo'] = g['Centro de costo'].str.strip().str.capitalize().replace(
        {'Comisión envio': 'Comisión envío', 'Comision envío': 'Comisión envío'})
    g['Modalidad'] = g['Modalidad'].str.strip().str.lower().map(MOD_GABRIELA).fillna('')

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
            print(f'[base] {huerf.sum()} filas de Gabriela sin venta que las reciba '
                  f'(${sin[huerf]["Valor"].sum():,.0f}) — quedan a nivel canal')
            sin.loc[huerf, ['Modalidad', 'w']] = ['Sin modalidad', 1.0]
            sin.loc[huerf, 'Línea de negocio'] = sin.loc[huerf, 'Línea de negocio'].fillna('Sin clasificar')
        sin['Valor'] = sin['Valor'] * sin['w']
        sin = sin.drop(columns=['w'])
    if len(con):
        ln = vent.groupby('Canal')['Línea de negocio'].agg(lambda s: s.mode().iat[0]).to_dict()
        con['Línea de negocio'] = con['Canal'].map(ln).fillna(con['Línea de negocio'])
    gab = pd.concat([x for x in (con, sin) if len(x)], ignore_index=True) if (len(con) or len(sin)) else pd.DataFrame(columns=COLS)
    if len(gab):
        gab['Año'] = gab['Mes'].str[:4].astype(int)
        gab['Fuente'] = 'Gabriela'
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
    base = armar_base(t, wg.get_all_values())
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
                     'venta, Comisión envío y Marketing.'],
        [f'{H_CON}', 'Se arma sola con una fórmula que apila las dos anteriores. No editar.'],
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
