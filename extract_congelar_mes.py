#!/usr/bin/env python3
"""
Congela un mes cerrado al parquet histórico, RE-EXTRAYÉNDOLO DE ODOO.

Reemplaza la versión vieja que leía de Turso (muerto desde may-2026). Usa el
mismo pipeline que el extract diario (`extract_mes_actual_a_parquet.py --mes`),
así el mes congelado incluye todo: fix de dedup NC, marketplace/yuju, El Volcán,
CMR, cargas manuales, etc.

Tras congelar un mes:
- Se reemplazan sus filas en `data/historico/ventas_historico.parquet`
  (todo lo de fuera del mes queda intacto — verificado).
- `CUTOFF_HISTORICO` en `views/shared.py` avanza al día 1 del mes siguiente.

Uso:
    python extract_congelar_mes.py 2026-06
    python extract_congelar_mes.py            # mes anterior al actual

Idempotente: re-extrae y reemplaza el mes; correrlo dos veces da el mismo result.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
SHARED_PATH = PROJECT_ROOT / 'views' / 'shared.py'
EXTRACT_SCRIPT = PROJECT_ROOT / 'extract_mes_actual_a_parquet.py'


def _mes_anterior() -> str:
    hoy = datetime.now()
    return (hoy.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')


def _rango_mes(yyyymm: str) -> tuple[str, str]:
    a, m = map(int, yyyymm.split('-'))
    desde = f"{a:04d}-{m:02d}-01"
    hasta = f"{a + 1:04d}-01-01" if m == 12 else f"{a:04d}-{m + 1:02d}-01"
    return desde, hasta


def _actualizar_cutoff_shared(nuevo_cutoff: str) -> bool:
    txt = SHARED_PATH.read_text(encoding='utf-8')
    nuevo = re.sub(r"CUTOFF_HISTORICO\s*=\s*['\"]\d{4}-\d{2}-\d{2}['\"]",
                   f"CUTOFF_HISTORICO = '{nuevo_cutoff}'", txt)
    if nuevo == txt:
        print(f"   [WARN] No se encontró CUTOFF_HISTORICO en {SHARED_PATH.name}")
        return False
    SHARED_PATH.write_text(nuevo, encoding='utf-8')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mes', nargs='?', default=None, help='YYYY-MM (default: mes anterior)')
    parser.add_argument('--allow-abierto', action='store_true',
                        help='Permite congelar un mes aún no terminado (para pruebas).')
    args = parser.parse_args()

    mes = args.mes or _mes_anterior()
    if not re.fullmatch(r'\d{4}-\d{2}', mes):
        print(f"Formato inválido: {mes}. Debe ser YYYY-MM"); sys.exit(1)
    desde, hasta = _rango_mes(mes)
    print(f"=== Congelando {mes} ({desde} a {hasta} excl.) desde Odoo ===")

    hoy = datetime.now().strftime('%Y-%m-%d')
    if hoy < hasta and not args.allow_abierto:
        print(f"[ERROR] El mes {mes} aún no termina (hoy={hoy}, fin={hasta}). Usa --allow-abierto si es intencional.")
        sys.exit(1)
    if not PARQUET_PATH.exists():
        print(f"[ERROR] No existe {PARQUET_PATH}"); sys.exit(1)

    # 1. Re-extraer el mes desde Odoo con el pipeline completo
    tmp = Path(tempfile.gettempdir()) / f"_congelar_{mes}.parquet"
    print(f"[1/4] Re-extrayendo {mes} de Odoo → {tmp.name} (3-5 min)...")
    r = subprocess.run([sys.executable, str(EXTRACT_SCRIPT), '--mes', mes,
                        '--out', str(tmp), '--skip-gate', '--source', 'odoo'],
                       cwd=str(PROJECT_ROOT))
    if r.returncode != 0 or not tmp.exists():
        print(f"[ERROR] La re-extracción de {mes} falló (rc={r.returncode})."); sys.exit(1)

    # 2. Cargar histórico + mes fresco (solo filas DEL mes; descarta spillover de bordes)
    h = pd.read_parquet(PARQUET_PATH)
    nu = pd.read_parquet(tmp)
    cols = list(h.columns)
    hfv = h['fecha_venta'].astype(str)
    nufv = nu['fecha_venta'].astype(str)
    fuera_mask = (hfv < desde) | (hfv >= hasta)          # todo lo que NO es el mes
    rows_fuera_pre = int(fuera_mask.sum())
    vneta_fuera_pre = float(pd.to_numeric(h.loc[fuera_mask, 'venta_neta'], errors='coerce').sum())

    nu_mes = nu[(nufv >= desde) & (nufv < hasta)].reindex(columns=cols)
    for c in cols:
        if nu_mes[c].isna().all() and h[c].dtype == object:
            nu_mes[c] = nu_mes[c].fillna('')
    if nu_mes.empty:
        print(f"[ERROR] La re-extracción no trajo filas de {mes}. Abortando (no piso el histórico)."); sys.exit(1)

    h_new = pd.concat([h[fuera_mask], nu_mes], ignore_index=True)
    print(f"[2/4] Mes {mes}: {int((~fuera_mask).sum()):,} filas viejas → {len(nu_mes):,} frescas")

    # 3. Verificación: NADA fuera del mes puede cambiar
    hnfv = h_new['fecha_venta'].astype(str)
    fuera_post = (hnfv < desde) | (hnfv >= hasta)
    rows_fuera_post = int(fuera_post.sum())
    vneta_fuera_post = float(pd.to_numeric(h_new.loc[fuera_post, 'venta_neta'], errors='coerce').sum())
    assert set(h_new.columns) == set(cols), "columnas cambiaron"
    assert rows_fuera_post == rows_fuera_pre and abs(vneta_fuera_post - vneta_fuera_pre) < 1, \
        f"CAMBIÓ data fuera de {mes}: {rows_fuera_pre}/{vneta_fuera_pre:,.0f} -> {rows_fuera_post}/{vneta_fuera_post:,.0f}"
    print(f"[3/4] Verif: data fuera de {mes} intacta ({rows_fuera_pre:,} filas / {vneta_fuera_pre:,.0f}) ✓")

    # 4. Backup + guardar + CUTOFF
    bak = PARQUET_PATH.with_suffix(f".parquet.bak_freeze_{mes}")
    shutil.copy2(PARQUET_PATH, bak)
    h_new.to_parquet(PARQUET_PATH, index=False, compression='zstd')
    vneta_mes = float(pd.to_numeric(nu_mes['venta_neta'], errors='coerce').sum())
    print(f"[4/4] Guardado ({len(h_new):,} filas). {mes} neto ${vneta_mes:,.0f}. Backup {bak.name}")
    if _actualizar_cutoff_shared(hasta):
        print(f"   CUTOFF_HISTORICO → '{hasta}'")
    try:
        tmp.unlink()
    except OSError:
        pass
    print(f"[OK] Mes {mes} congelado desde Odoo.")


if __name__ == '__main__':
    main()
