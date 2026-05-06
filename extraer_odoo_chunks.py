"""Extrae ventas de Odoo en chunks de 3 dias e inserta en Maestra SQLite."""
import sys
import traceback
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent / 'finanzas-unionx' / 'backend'))

import pandas as pd
from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config
from actualizar_raw_historico import insertar_en_maestra, DB_LOCAL, DB_PATH


def main():
    try:
        print("Conectando a Odoo...")
        odoo = OdooClient(url=Config.ODOO_URL, db=Config.ODOO_DB,
                          username=Config.ODOO_USER, password=Config.ODOO_PASSWORD)
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        print("OK\n")

        db = DB_LOCAL if DB_LOCAL.exists() else DB_PATH
        print(f"DB: {db}\n")

        inicio = datetime(2026, 4, 12)
        fin_total = datetime(2026, 4, 14, 23, 59, 59)
        chunk_dias = 1
        all_dfs = []

        current = inicio
        chunk_num = 0
        while current < fin_total:
            chunk_num += 1
            chunk_fin = min(current + timedelta(days=chunk_dias) - timedelta(seconds=1), fin_total)
            p_ini = current.strftime('%Y-%m-%d %H:%M:%S')
            p_fin = chunk_fin.strftime('%Y-%m-%d %H:%M:%S')

            print(f"--- Chunk {chunk_num}: {p_ini} a {p_fin} ---")
            try:
                df = service.extract_to_raw_format(
                    p_ini, p_fin,
                    progress_callback=lambda pct, lbl: print(f"  {pct}% {lbl}")
                )
                if len(df) > 0:
                    total = insertar_en_maestra(df, db)
                    print(f"  [OK] +{len(df):,} filas -> DB total: {total:,}")
                    all_dfs.append(df)
                else:
                    print(f"  Sin datos")
            except Exception as e:
                print(f"  [ERROR chunk {chunk_num}] {type(e).__name__}: {e}")
                traceback.print_exc()

            current = chunk_fin + timedelta(seconds=1)
            print()

        total_filas = sum(len(d) for d in all_dfs)
        print(f"=== TOTAL: {total_filas:,} filas en {chunk_num} chunks ===")
        if all_dfs:
            df_all = pd.concat(all_dfs, ignore_index=True)
            venta = df_all['Venta bruta'].sum()
            margen = df_all['Mg final'].sum()
            print(f"Venta: ${venta:,.0f}")
            print(f"Margen: ${margen:,.0f}")
            if venta > 0:
                print(f"% Margen: {margen/venta*100:.1f}%")

    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    main()
