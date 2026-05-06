#!/usr/bin/env python3
"""
Script para generar reporte de ventas de abril hasta ayer (2026-04-13)
Usa VentasService con los totales netos corregidos.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Agregar backend al path
backend_path = Path(__file__).parent / 'finanzas-unionx' / 'backend'
sys.path.insert(0, str(backend_path))

from app.core.odoo_client import OdooClient
from app.services.ventas_service import VentasService
from app.config import Config
import pandas as pd

def generar_reporte():
    """Genera reporte de ventas con totales netos corregidos"""

    print("\n" + "="*80)
    print("GENERADOR DE REPORTE DE VENTAS - ABRIL 2026 (hasta ayer)")
    print("="*80 + "\n")

    # Fechas
    periodo_inicio = "2026-04-01 00:00:00"
    # Ayer = 2026-04-13 (hoy es 2026-04-14)
    periodo_fin = "2026-04-13 23:59:59"

    print(f"Período: {periodo_inicio} a {periodo_fin}\n")

    try:
        # Crear cliente Odoo
        print("[1/4] Conectando a Odoo...")
        odoo = OdooClient(
            url=Config.ODOO_URL,
            db=Config.ODOO_DB,
            username=Config.ODOO_USER,
            password=Config.ODOO_PASSWORD
        )
        print("      [OK] Conectado\n")

        # Crear servicio
        print("[2/4] Inicializando VentasService...")
        service = VentasService(odoo, Config.PLANILLAS_DIR)
        print("      [OK] Servicio listo\n")

        # Extraer datos con callback de progreso
        print("[3/4] Extrayendo datos de Odoo...")
        def progress_callback(pct, label):
            print(f"      {pct}% - {label}")

        data = service.extract(
            periodo_inicio,
            periodo_fin,
            progress_callback=progress_callback
        )

        df = data['data']
        resumenes = data['resumenes']
        kpis = service._calcular_kpis(df)

        print("\n[4/4] Generando reportes...\n")

        # ===== RESUMEN EJECUTIVO =====
        print("="*80)
        print("RESUMEN EJECUTIVO - ABRIL 2026 (hasta 13-04)")
        print("="*80 + "\n")

        print(f"Total de órdenes:        {kpis['total_ordenes']:,}")
        print(f"Total de líneas:         {kpis['total_lineas']:,}")
        print(f"\nVenta Neta (NETA):       ${kpis['venta_neta']:,.2f}")
        print(f"Costo Total:             ${kpis['costo_total']:,.2f}")
        print(f"Margen Directo:          ${kpis['margen_directo']:,.2f}")
        print(f"Margen Final:            ${kpis['margen_final']:,.2f}")
        print(f"% Margen Final:          {kpis['pct_margen_final']:.1f}%\n")

        # ===== RESUMEN POR CANAL =====
        print("="*80)
        print("RESUMEN POR CANAL DE VENTA")
        print("="*80 + "\n")

        canal_resumen = resumenes['canal'].copy()
        canal_resumen.columns = ['Canal', 'Venta Neta', 'Costo', 'Margen Directo',
                                 'Comisión', 'Logística', 'Margen Final', '% Margen']

        # Formatear para presentación
        pd.options.display.float_format = '{:,.2f}'.format

        print(canal_resumen.to_string(index=False))
        print()

        # ===== GENERAR EXCEL =====
        print("\n" + "="*80)
        print("GENERANDO ARCHIVOS...")
        print("="*80 + "\n")

        from app.core.excel_builder import ExcelBuilder

        excel_bytes = ExcelBuilder.build(
            df,
            resumenes.get('linea'),
            resumenes.get('canal'),
            resumenes.get('categoria'),
            resumenes.get('bodega'),
            'abril_2026_hasta_13'
        )

        # Guardar Excel
        output_dir = Path(__file__).parent / 'data' / 'outputs'
        output_dir.mkdir(parents=True, exist_ok=True)

        excel_file = output_dir / f'reporte_ventas_abril_2026_hasta_13_NETO.xlsx'
        with open(excel_file, 'wb') as f:
            f.write(excel_bytes.getvalue())

        print(f"[OK] Excel generado: {excel_file}")
        print(f"  Tamaño: {excel_file.stat().st_size / 1024:.1f} KB")

        # CSV también
        csv_file = output_dir / f'reporte_ventas_abril_2026_hasta_13_NETO.csv'
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"\n[OK] CSV generado: {csv_file}")
        print(f"  Filas: {len(df):,}")

        print("\n" + "="*80)
        print("[OK] REPORTE COMPLETADO EXITOSAMENTE")
        print("="*80 + "\n")

        # Mostrar estadísticas por canal en tabla bonita
        print("\nDETALLES POR CANAL:\n")
        for idx, row in canal_resumen.iterrows():
            print(f"{row['Canal']:20} | Venta: ${row['Venta Neta']:>15,.0f} | "
                  f"Margen: ${row['Margen Final']:>12,.0f} ({row['% Margen']:>5.1f}%)")

        print("\n" + "="*80 + "\n")

        return excel_file, csv_file

    except Exception as e:
        print(f"\n[ERROR]: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, None

if __name__ == '__main__':
    excel_file, csv_file = generar_reporte()
    if excel_file:
        print(f"Archivos generados:")
        print(f"  - {excel_file}")
        print(f"  - {csv_file}")
