#!/usr/bin/env python3
"""
Congela un mes cerrado: lo descarga desde Turso y lo agrega al parquet histórico.

Reduce drásticamente la cantidad de datos que el dashboard tiene que pedir a
Turso en cada arranque (cada cold start de Streamlit Cloud el SQLite local se
reconstruye trayendo TODO lo post-CUTOFF, lo cual da ReadTimeout cuando hay
muchas filas).

Tras congelar un mes:
- Se agrega al `data/historico/ventas_historico.parquet`
- `CUTOFF_HISTORICO` en `views/shared.py` avanza al mes siguiente
- Dashboard solo tiene que traer de Turso el mes corriente (~7-20K filas)

Uso:
    python extract_congelar_mes.py 2026-04
    python extract_congelar_mes.py            # automatico: mes anterior al actual

Idempotente: si el mes ya estaba congelado, no duplica.
"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).parent
PARQUET_PATH = PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet'
SHARED_PATH = PROJECT_ROOT / 'views' / 'shared.py'

COLS = ['tipo_movimiento', 'bodega', 'documento', 'fecha_documento', 'pedido',
        'estado_pedido', 'tipo_despacho', 'sku', 'canal', 'fecha_venta',
        'hora_venta', 'producto', 'categoria_macro', 'categoria_padre',
        'categoria_hijo', 'categoria_comercial', 'estado_sku', 'pack', 'marca',
        'proveedor', 'tipo_marca', 'tipo_compra', 'tipo_negocio', 'kam',
        'estado_canal', 'anio_venta', 'mes_venta', 'semana_venta', 'dia_semana',
        'hora_venta_num', 'cantidad', 'venta_bruta', 'costo_unitario',
        'costo_total', 'margen_front', 'comision_pct', 'comision', 'logistica',
        'marketing', 'margen_final', 'venta_neta']


def _mes_anterior() -> str:
    """Devuelve YYYY-MM del mes anterior al actual."""
    hoy = datetime.now()
    primer_dia_actual = hoy.replace(day=1)
    ultimo_dia_anterior = primer_dia_actual - timedelta(days=1)
    return ultimo_dia_anterior.strftime('%Y-%m')


def _rango_mes(yyyymm: str) -> tuple[str, str]:
    """Devuelve (desde, hasta) en formato YYYY-MM-DD del mes."""
    año, mes = map(int, yyyymm.split('-'))
    desde = f"{año:04d}-{mes:02d}-01"
    if mes == 12:
        hasta = f"{año + 1:04d}-01-01"
    else:
        hasta = f"{año:04d}-{mes + 1:02d}-01"
    return desde, hasta


def _load_env_from_dotenv():
    """Carga LIBSQL_* desde .env si no están en env (uso local)."""
    if os.environ.get('LIBSQL_URL') and os.environ.get('LIBSQL_AUTH_TOKEN'):
        return
    env_path = PROJECT_ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            k = k.strip()
            if k in ('LIBSQL_URL', 'LIBSQL_AUTH_TOKEN') and not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


def _turso_query(sql: str, retries: int = 5, timeout_s: int = 120) -> dict:
    url = os.environ['LIBSQL_URL'].rstrip('/')
    tok = os.environ['LIBSQL_AUTH_TOKEN']
    hdr = {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}
    body = {'requests': [{'type': 'execute', 'stmt': {'sql': sql}}, {'type': 'close'}]}
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{url}/v2/pipeline", json=body, headers=hdr, timeout=timeout_s)
            r.raise_for_status()
            return r.json()['results'][0]['response']['result']
        except (requests.exceptions.RequestException, KeyError) as e:
            last = e
            import time
            wait = min(30, 2 + i * 5)  # 2, 7, 12, 17, 22s
            print(f"   [retry {i+1}/{retries}] {type(e).__name__}: esperando {wait}s...", flush=True)
            time.sleep(wait)
    raise last


def _descargar_mes_de_turso(desde: str, hasta: str, chunk_size: int = 5000) -> pd.DataFrame:
    """Descarga todas las filas de ventas entre [desde, hasta) en chunks."""
    print(f"[1/4] Descargando Turso ventas WHERE fecha_venta BETWEEN '{desde}' AND '{hasta}' (excl)...")
    cols_csv = ','.join(COLS)
    last_rowid = 0
    chunks = []
    n = 0
    while True:
        sql = (f"SELECT rowid, {cols_csv} FROM ventas "
               f"WHERE fecha_venta >= '{desde}' AND fecha_venta < '{hasta}' "
               f"AND rowid > {last_rowid} ORDER BY rowid LIMIT {chunk_size}")
        result = _turso_query(sql)
        rows = result['rows']
        if not rows:
            break
        flat = []
        for r in rows:
            vals = [c.get('value') if isinstance(c, dict) else c for c in r]
            last_rowid = int(vals[0])
            flat.append(vals[1:])  # sin rowid
        chunks.append(pd.DataFrame(flat, columns=COLS))
        n += len(rows)
        print(f"   chunk {len(chunks)}: +{len(rows):,} (total {n:,})")
        if len(rows) < chunk_size:
            break
    if not chunks:
        return pd.DataFrame(columns=COLS)
    return pd.concat(chunks, ignore_index=True)


def _actualizar_cutoff_shared(nuevo_cutoff: str):
    """Reemplaza el valor de CUTOFF_HISTORICO en views/shared.py."""
    txt = SHARED_PATH.read_text(encoding='utf-8')
    nuevo = re.sub(
        r"CUTOFF_HISTORICO\s*=\s*['\"]\d{4}-\d{2}-\d{2}['\"]",
        f"CUTOFF_HISTORICO = '{nuevo_cutoff}'",
        txt,
    )
    if nuevo == txt:
        print(f"   [WARN] No se encontró CUTOFF_HISTORICO en {SHARED_PATH.name} — revisar manualmente")
        return False
    SHARED_PATH.write_text(nuevo, encoding='utf-8')
    return True


def main():
    _load_env_from_dotenv()
    if not os.environ.get('LIBSQL_URL') or not os.environ.get('LIBSQL_AUTH_TOKEN'):
        print("[ERROR] LIBSQL_URL/LIBSQL_AUTH_TOKEN no setados (ni en env ni en .env)")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument('mes', nargs='?', default=None,
                        help='YYYY-MM a congelar. Si se omite, mes anterior al actual.')
    parser.add_argument('--force', action='store_true',
                        help='Forzar sobreescritura aunque el parquet ya tenga más filas '
                             '(perderá cargas manuales). Default: bloquear.')
    args = parser.parse_args()

    mes = args.mes or _mes_anterior()
    if not re.fullmatch(r'\d{4}-\d{2}', mes):
        print(f"Formato invalido: {mes}. Debe ser YYYY-MM")
        sys.exit(1)

    desde, hasta = _rango_mes(mes)
    print(f"=== Congelando mes {mes} ({desde} a {hasta} excl.) ===\n")

    # 1. Verificar que el mes esté cerrado (i.e., hoy >= hasta)
    hoy = datetime.now().strftime('%Y-%m-%d')
    if hoy < hasta:
        print(f"[ERROR] El mes {mes} aún no terminó (hoy={hoy}, fin={hasta}). Abortando.")
        sys.exit(1)

    # 2. Cargar parquet histórico
    if not PARQUET_PATH.exists():
        print(f"[ERROR] No existe {PARQUET_PATH}")
        sys.exit(1)
    df_hist = pd.read_parquet(PARQUET_PATH)
    print(f"[1/4] Parquet existente: {len(df_hist):,} filas")

    # 3. Si ya hay filas del mes en parquet → idempotencia
    max_hist = pd.to_datetime(df_hist['fecha_venta'], errors='coerce').max()
    if pd.notna(max_hist) and max_hist >= pd.Timestamp(hasta):
        print(f"   El parquet ya cubre hasta {max_hist.date()} (>= {hasta}). Nada que hacer.")
        sys.exit(0)

    # 4. Descargar mes desde Turso
    df_nuevo = _descargar_mes_de_turso(desde, hasta)
    print(f"\n[2/4] Filas nuevas de Turso: {len(df_nuevo):,}")
    if df_nuevo.empty:
        print("   No hay filas para congelar. Saliendo.")
        sys.exit(0)

    # 4b. LOCK: si el parquet local ya tiene MÁS filas que Turso para el mismo
    # mes, significa que recibió cargas manuales (ej. desde Drive maestro) y
    # NO debe sobreescribirse desde Turso (que podría estar incompleto).
    fechas_hist = pd.to_datetime(df_hist['fecha_venta'], errors='coerce')
    n_parquet_mes = int(((fechas_hist >= pd.Timestamp(desde))
                         & (fechas_hist < pd.Timestamp(hasta))).sum())
    if n_parquet_mes > len(df_nuevo):
        venta_parquet = float(
            pd.to_numeric(
                df_hist.loc[(fechas_hist >= pd.Timestamp(desde))
                            & (fechas_hist < pd.Timestamp(hasta)), 'venta_bruta'],
                errors='coerce',
            ).fillna(0).sum()
        )
        venta_turso = float(
            pd.to_numeric(df_nuevo.get('venta_bruta', pd.Series(dtype=float)),
                          errors='coerce').fillna(0).sum()
        )
        print()
        print("=" * 80)
        print(f"[LOCK] El parquet local para {mes} tiene MÁS filas que Turso:")
        print(f"   Parquet local: {n_parquet_mes:,} filas, venta ${venta_parquet:,.0f}")
        print(f"   Turso ahora:   {len(df_nuevo):,} filas, venta ${venta_turso:,.0f}")
        print()
        print("Esto suele indicar que el parquet tiene cargas manuales desde el")
        print("Drive maestro (canales como El Volcán, CMR, Sawa, ajustes Falabella, etc.)")
        print("que NO están en Turso porque el extractor no los genera.")
        print()
        print("Si querés FORZAR la sobrescritura desde Turso (perderás esos datos)")
        print("ejecuta con --force.")
        print("=" * 80)
        if not getattr(args, 'force', False):
            sys.exit(2)
        print("[FORCE] Sobreescritura forzada por flag --force. Continuando…")

    # 4b. Coercionar dtypes para que match con parquet histórico (evitar errores Arrow)
    for col in df_nuevo.columns:
        if col in df_hist.columns:
            target = df_hist[col].dtype
            try:
                df_nuevo[col] = df_nuevo[col].astype(target)
            except (ValueError, TypeError):
                # Numérico con strings: coerce → NaN
                if pd.api.types.is_numeric_dtype(target):
                    df_nuevo[col] = pd.to_numeric(df_nuevo[col], errors='coerce')
                    if pd.api.types.is_integer_dtype(target):
                        df_nuevo[col] = df_nuevo[col].fillna(0).astype(target)
                else:
                    df_nuevo[col] = df_nuevo[col].astype(str)

    # 5. Concatenar + dedup por (fecha_venta, pedido, sku, documento)
    df_total = pd.concat([df_hist, df_nuevo], ignore_index=True)
    antes = len(df_total)
    df_total = df_total.drop_duplicates(
        subset=['fecha_venta', 'pedido', 'sku', 'documento', 'tipo_movimiento'],
        keep='last',
    )
    dedup = antes - len(df_total)
    print(f"[3/4] Dedup: {dedup:,} filas duplicadas removidas. Total final: {len(df_total):,}")

    # 6. Sort por fecha_venta + guardar
    df_total['fecha_venta'] = pd.to_datetime(df_total['fecha_venta'], errors='coerce')
    df_total = df_total.sort_values('fecha_venta', kind='stable')
    df_total['fecha_venta'] = df_total['fecha_venta'].dt.strftime('%Y-%m-%d')

    # Compactar tipos antes de guardar (crítico para RAM Streamlit Cloud)
    from compactar_parquet import compactar_ventas, mem_mb
    df_save = compactar_ventas(df_total[COLS])
    df_save.to_parquet(PARQUET_PATH, index=False)
    print(f"[4/4] Guardado {PARQUET_PATH} ({len(df_save):,} filas, {mem_mb(df_save):.0f} MB RAM)")

    # 7. Actualizar CUTOFF_HISTORICO en views/shared.py
    nuevo_cutoff = hasta  # el día 1 del mes siguiente
    if _actualizar_cutoff_shared(nuevo_cutoff):
        print(f"   CUTOFF_HISTORICO actualizado a '{nuevo_cutoff}' en views/shared.py")

    print(f"\n[OK] Mes {mes} congelado. Dashboard ahora pedirá a Turso solo desde {nuevo_cutoff}.")


if __name__ == '__main__':
    main()
