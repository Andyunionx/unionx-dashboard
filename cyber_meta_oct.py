# -*- coding: utf-8 -*-
"""Meta del Cyber Octubre 2026 → data/planificacion/plan_cyber_oct2026.json.

Lee la hoja META de la planificación comercial (Drive "Planificacion_Cyber_Oct2026.xlsx",
columna "Meta Cyber Bruta" por canal) y la deja en el JSON que usa el pulso Cyber.
La apertura por día la manda Nicole: mientras no llegue, el pulso reparte la meta de
cada canal con la curva del mismo canal en el Cyber de octubre 2025 (lun 6 → dom 12).
Cuando llegue, se carga en "meta_dia" (7 montos brutos, lun 5 → dom 11) y el pulso
reescala cada día a ese total.

Uso: python cyber_meta_oct.py            (baja de Drive con drive_oauth_token.json)
     python cyber_meta_oct.py <xlsx>     (desde un archivo local; si es la planificación v8 de Nicole,
                                          Cumplimiento_Plan_Cyber_W41.xlsx, lee la hoja "Por canal")
Vigente desde 04-10 (Andrés): la planificación v8 de Nicole. La planilla del Drive ya no se usa.
"""
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).parent
PLAN_ID = '1DL78bm8UepEPX_kcrvwkvQDSnjGOw_pO'
OUT = ROOT / 'data' / 'planificacion' / 'plan_cyber_oct2026.json'
# nombre en la planificación → canal del RAW
CANAL_RAW = {'Unionx web': 'UnionX web', 'El volcan': 'El Volcan', 'Latam': 'LATAM Pass', 'Global reward': 'Global Reward'}


def bajar_plan():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    c = Credentials.from_authorized_user_file(str(ROOT / 'drive_oauth_token.json'))
    if not c.valid:
        c.refresh(Request())
    d = build('drive', 'v3', credentials=c)
    meta = d.files().get(fileId=PLAN_ID, fields='name,modifiedTime', supportsAllDrives=True).execute()
    b = io.BytesIO()
    dl = MediaIoBaseDownload(b, d.files().get_media(fileId=PLAN_ID, supportsAllDrives=True))
    done = False
    while not done:
        _, done = dl.next_chunk()
    b.seek(0)
    return b, meta


def leer_meta(fuente):
    ws = openpyxl.load_workbook(fuente, read_only=True, data_only=True)['META']
    filas = list(ws.iter_rows(values_only=True))
    head = [str(x).strip() if x is not None else '' for x in filas[0]]
    ic, im = head.index('Canal'), head.index('Meta Cyber Bruta')
    metas, total = {}, None
    for r in filas[1:]:
        canal = str(r[ic] or '').strip()
        if not canal:
            break                      # fin de la tabla (abajo hay notas sueltas)
        v = r[im]
        if not isinstance(v, (int, float)):
            continue
        if canal.lower() == 'total general':
            total = float(v)
            continue
        metas[CANAL_RAW.get(canal, canal)] = round(float(v))
    return metas, total


def leer_v8(fuente):
    """Planificación v8 de Nicole (Cumplimiento_Plan_Cyber_W41.xlsx, hoja 'Por canal', columna 'Plan $', bruto)."""
    import pandas as pd
    pc = pd.read_excel(fuente, 'Por canal')
    pc = pc[pc['Canal'].notna() & (pc['Canal'] != 'Total general')]
    metas = {CANAL_RAW.get(str(c).strip(), str(c).strip()): round(float(v)) for c, v in zip(pc['Canal'], pc['Plan $']) if float(v or 0) > 0}
    return metas, float(pc['Plan $'].sum())


def main():
    if len(sys.argv) > 1:
        fuente, info = sys.argv[1], {'name': Path(sys.argv[1]).name, 'modifiedTime': ''}
    else:
        fuente, info = bajar_plan()
    es_v8 = 'Por canal' in openpyxl.load_workbook(fuente, read_only=True).sheetnames
    metas, total = leer_v8(fuente) if es_v8 else leer_meta(fuente)
    suma = sum(metas.values())
    # La planilla calcula cada canal como venta neta × 1,19 × máx(peso W41, 60%), y la fila
    # "Total general" con la misma fórmula sobre el total (peso 60%): no son iguales. El pulso
    # usa la suma por canal; el total de la planilla queda registrado como referencia.
    if total is not None and abs(suma - total) >= 10:
        print(f'[WARN] suma por canal ${suma:,.0f} ≠ "Total general" de la planilla ${total:,.0f}')
    previo = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    data = {
        'evento': 'Cyber Octubre 2026 (lun 5 → dom 11)',
        'fuente': (f"{info['name']} · hoja 'Por canal' · columna 'Plan $' (planificación v8 de Nicole, bruta)" if es_v8
                   else f"{info['name']} · hoja META · columna 'Meta Cyber Bruta' (venta bruta, con IVA)"),
        'plan_modificado': info.get('modifiedTime', ''),
        'actualizado': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'meta_total_bruta': round(suma),
        'total_general_planilla': round(total) if total is not None else None,
        'metas_canal': dict(sorted(metas.items(), key=lambda kv: -kv[1])),
        # apertura por día de Nicole (7 montos brutos lun→dom). Vacío = curva Cyber oct-2025.
        'meta_dia': previo.get('meta_dia', []),
        # metas por área (ej. Nicole en neta con apertura diaria): se conservan al re-leer la planilla
        'grupos': previo.get('grupos', {}),
        # meta de margen final: regla pareja sobre la venta neta (Andrés 05-10); se conserva al re-leer la planilla
        'margen_final_meta_pct': previo.get('margen_final_meta_pct'),
        'fuente_margen_final': previo.get('fuente_margen_final', ''),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'[meta Cyber oct] {len(metas)} canales · ${suma:,.0f} bruto → {OUT}')


if __name__ == '__main__':
    main()
