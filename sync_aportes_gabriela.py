# -*- coding: utf-8 -*-
"""Sincroniza el Control de Aportes de Andrés con la copia de Gabriela (rentabilidad).

Andrés mantiene «Control Aportes Uniox y Marketing.xlsx» en data/planillas (su PC,
sincronizado a su Drive). Gabriela lo usa en la carpeta LIQUIDACIONES MKP/APORTES
para la macro de rentabilidad. Pedido de Andrés (11-nov-2026): que el agente de
rentabilidad lo revise cada semana y suba las modificaciones.

Qué hace:
  1. Compara el md5 de los dos archivos en Drive. Si son iguales, no hace nada.
  2. Si la copia de Gabriela cambió desde la última sincronización (alguien la
     editó ahí), NO la pisa: avisa y termina con código 2.
  3. Si no, mapea qué cambió en la hoja «Aportes» (filas nuevas, celdas que
     cambiaron) y sube el archivo de Andrés como NUEVA VERSIÓN de la copia de
     Gabriela. Así el link no cambia. La versión anterior queda fijada en el historial.

Uso:
    python sync_aportes_gabriela.py            # revisa y sube si hay cambios
    python sync_aportes_gabriela.py --dry-run  # solo muestra qué cambió
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).parent))
from drive_user_helpers import _service, descargar_archivo  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

ORIGEN = '1f4qfs18k3QFVKHluz-ar_qSRe23YtukO'   # Mi unidad/.../UNION X - IA/data/planillas (Andrés)
DESTINO = '1N-3lMzmH9QQyJRs-pOzkzOvzpqDziF9T'  # LIQUIDACIONES MKP/APORTES (Gabriela)
HOJA = 'Aportes'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _meta(d, fid):
    return d.files().get(fileId=fid, supportsAllDrives=True,
                         fields='id,name,md5Checksum,modifiedTime,headRevisionId,appProperties,'
                                'lastModifyingUser(emailAddress)').execute()


def _aportes(path):
    df = pd.read_excel(path, sheet_name=HOJA).dropna(how='all')
    return df.reset_index(drop=True)


def _txt(v):
    if pd.isna(v):
        return ''
    if isinstance(v, float):
        return f'{v:.2f}'
    return str(v).strip()


def mapear(viejo, nuevo):
    """Resumen de cambios en la hoja Aportes (fila a fila: la planilla crece hacia abajo)."""
    lin = []
    n = min(len(viejo), len(nuevo))
    celdas = []
    for i in range(n):
        for c in nuevo.columns:
            a = _txt(viejo.iloc[i].get(c)) if c in viejo.columns else ''
            b = _txt(nuevo.iloc[i].get(c))
            if a != b:
                celdas.append((i + 2, c, a, b))
    nuevas = nuevo.iloc[n:]
    if len(nuevas):
        lin.append(f'Filas nuevas: {len(nuevas)}')
        g = nuevas.groupby(['Año', 'Mes', 'Retail'], dropna=False)['Provisión Neta'].agg(['size', 'sum'])
        for (an, me, re), r in g.iterrows():
            monto = f'{r["sum"]:,.0f}'.replace(',', '.')
            lin.append(f'  {int(an) if pd.notna(an) else "?"}-{int(me) if pd.notna(me) else "?":02} {re}: '
                       f'{int(r["size"])} fila(s), provisión ${monto}')
    if len(viejo) > len(nuevo):
        lin.append(f'OJO: la planilla nueva tiene {len(viejo) - len(nuevo)} fila(s) MENOS que la copia de Gabriela')
    if celdas:
        filas = sorted({c[0] for c in celdas})
        lin.append(f'Celdas modificadas: {len(celdas)} en {len(filas)} fila(s)')
        for f, c, a, b in celdas[:40]:
            lin.append(f'  fila {f} · {c}: «{a}» → «{b}»')
        if len(celdas) > 40:
            lin.append(f'  … y {len(celdas) - 40} más')
    if not lin:
        lin.append('Sin cambios en la hoja Aportes (cambió otra hoja o el formato)')
    return lin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    d = _service()
    src, dst = _meta(d, ORIGEN), _meta(d, DESTINO)
    print(f'Andrés  : {src["modifiedTime"][:16]} md5 {src["md5Checksum"][:8]}')
    print(f'Gabriela: {dst["modifiedTime"][:16]} md5 {dst["md5Checksum"][:8]}')
    if src['md5Checksum'] == dst['md5Checksum']:
        print('Sin cambios: la copia de Gabriela ya está al día.')
        return 0

    sync = (dst.get('appProperties') or {}).get('sync_md5')
    if sync and dst['md5Checksum'] != sync:
        quien = (dst.get('lastModifyingUser') or {}).get('emailAddress', '?')
        print(f'NO SE SUBE: la copia de Gabriela cambió después de la última sincronización '
              f'(último cambio: {quien}, {dst["modifiedTime"][:16]}). Revisar a mano para no pisar su trabajo.')
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        f_src = descargar_archivo(ORIGEN, Path(tmp) / 'andres.xlsx')
        f_dst = descargar_archivo(DESTINO, Path(tmp) / 'gabriela.xlsx')
        resumen = mapear(_aportes(f_dst), _aportes(f_src))
        print('\n'.join(resumen))
        if a.dry_run:
            print('[dry-run] no se sube nada.')
            return 0
        d.revisions().update(fileId=DESTINO, revisionId=dst['headRevisionId'],
                             body={'keepForever': True}).execute()
        r = d.files().update(
            fileId=DESTINO, supportsAllDrives=True, fields='md5Checksum,modifiedTime',
            media_body=MediaFileUpload(str(f_src), mimetype=XLSX, resumable=False),
            body={'appProperties': {'sync_md5': src['md5Checksum'],
                                    'sync_fecha': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}},
        ).execute()
    ok = r['md5Checksum'] == src['md5Checksum']
    print(f'Subido como nueva versión: md5 {r["md5Checksum"][:8]} {"= Andrés" if ok else "DISTINTO"}')
    resumen_md = os.environ.get('GITHUB_STEP_SUMMARY')
    if resumen_md:
        with open(resumen_md, 'a', encoding='utf-8') as fh:
            fh.write('### Control de Aportes → carpeta de Gabriela\n\n```\n' + '\n'.join(resumen) + '\n```\n')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
