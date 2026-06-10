"""Genera 'Reporte Ventas Empresa LIVE.xlsx' actualizando la Raw del archivo
original con datos frescos del parquet, manteniendo SOLO la pivot Resumen TD.

Approach: manipulacion ZIP segura.
  1. Carga el archivo original como solo-lectura (no se modifica).
  2. Genera archivo nuevo conservando:
     - sheet1 (Resumen TD) con su pivot
     - sheet3 (Raw) con datos frescos del parquet (2025-2026)
     - pivotTable1 + pivotCacheDefinition3 (la cache de Resumen TD)
  3. Marca refreshOnLoad=1 para que Excel actualice la pivot al abrir.
  4. Elimina: sheets 2, 4, 5, 6, 7 + caches 1 y 2 + calcChain.xml +
     definedNames huerfanos.

Salida: data/outputs/Reporte Ventas Empresa LIVE.xlsx
"""
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

PROJECT_ROOT = Path(__file__).resolve().parent
ORIGINAL = PROJECT_ROOT / 'data' / 'planillas' / 'Reporte Ventas Empresa 2026 VS 2025 RAW.xlsx'
# Carpeta Drive "Reporte Automático RAW" (id fijo, compartida con OAuth user)
DRIVE_CARPETA_ID = '18RKgdGwWGM8tEGqltcrruCPB-LaTwZxx'
NOMBRE_LIVE = 'Reporte Ventas Empresa LIVE.xlsx'
ANIO_TY = 2026  # Ano TY (This Year). LY = ANIO_TY - 1.
# Output local: en GH Actions usa /tmp, local usa data/outputs/
if os.environ.get('GITHUB_ACTIONS') == 'true':
    OUTPUT = Path('/tmp') / NOMBRE_LIVE
else:
    OUTPUT = PROJECT_ROOT / 'data' / 'outputs' / NOMBRE_LIVE

# 56 columnas en el ORDEN EXACTO del original (validado contra archivo)
RAW_COLUMNS = [
    'Fecha Comp', 'Tipo Movimiento', 'Bodega', 'Documento', 'Fecha Documento',
    'Pedido', 'Estado Pedido', 'Tipo Despacho', 'SKU', 'Canal',
    'Fecha Venta', 'Hora Venta', 'Producto', 'Categoría macro',
    'Categoría padre', 'Categoría hijo', 'Categoría comercial', 'Estado SKU',
    'Pack', 'Marca', 'Proveedor', 'Tipo Marca', 'Tipo Compra', 'Tipo Negocio',
    'KAM', 'Estado Canal', 'Año venta', 'Mes venta', 'Semana venta',
    'Día semana', 'Hora venta', 'Cantidad TY', 'Venta bruta TY',
    'Costo Unitario TY', 'Costo Total TY', 'Margen Front TY', 'Comision % TY',
    'Comisión TY', 'Logística TY', 'Marketing TY', 'Cantidad LY',
    'Venta bruta LY', 'Costo Unitario LY', 'Costo Total LY', 'Margen Front LY',
    'Comision % LY', 'Comisión LY', 'Logística LY', 'Marketing LY',
    'Año', 'Mes', 'Semana', 'Fecha Compara', 'Week', 'Obs', None,
]

# Mapeo columna XLSX -> nombre en parquet
PARQUET_MAP = {
    'Tipo Movimiento': 'tipo_movimiento',
    'Bodega': 'bodega',
    'Documento': 'documento',
    'Pedido': 'pedido',
    'Estado Pedido': 'estado_pedido',
    'Tipo Despacho': 'tipo_despacho',
    'SKU': 'sku',
    'Canal': 'canal',
    'Fecha Venta': 'fecha_venta',
    'Producto': 'producto',
    'Categoría macro': 'categoria_macro',
    'Categoría padre': 'categoria_padre',
    'Categoría hijo': 'categoria_hijo',
    'Categoría comercial': 'categoria_comercial',
    'Estado SKU': 'estado_sku',
    'Pack': 'pack',
    'Marca': 'marca',
    'Proveedor': 'proveedor',
    'Tipo Marca': 'tipo_marca',
    'Tipo Compra': 'tipo_compra',
    'Tipo Negocio': 'tipo_negocio',
    'KAM': 'kam',
    'Estado Canal': 'estado_canal',
}


def cargar_raw_parquet() -> pd.DataFrame:
    """Lee parquet (hist + mes_actual), filtra a 2025-2026, prepara 56 cols."""
    h = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet')
    m = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet')
    cols = [c for c in m.columns if c in h.columns]
    df = pd.concat([h[cols], m], ignore_index=True)

    df['fv'] = pd.to_datetime(df['fecha_venta'], errors='coerce')
    df['anio'] = df['fv'].dt.year
    df = df[df['anio'].isin([2025, 2026])].copy()

    # Construir DataFrame con las 56 columnas del Excel
    out = pd.DataFrame(index=df.index)

    # Columna 1: Fecha Comp para alinear LY a TY (sin meter fechas en TY+1)
    # - Filas LY (2025): fecha_venta + 364 dias -> 2026 (alinea con TY)
    # - Filas TY (2026): fecha_venta misma (sin alterar, ya esta en TY)
    fc = df['fv'].copy()
    es_ly = df['anio'] < ANIO_TY
    fc.loc[es_ly] = fc.loc[es_ly] + pd.Timedelta(days=364)
    out['Fecha Comp'] = fc.dt.strftime('%Y-%m-%d')

    # Columnas mapeadas directo del parquet
    for excel_col, parq_col in PARQUET_MAP.items():
        if parq_col in df.columns:
            out[excel_col] = df[parq_col].astype('object').fillna('')
        else:
            out[excel_col] = ''

    # Fecha Documento: tomar fecha_venta como fallback
    out['Fecha Documento'] = df['fv'].dt.strftime('%Y-%m-%d')
    # Hora Venta como texto
    if 'hora_venta' in df.columns:
        out['Hora Venta'] = df['hora_venta'].astype('object').fillna('')
    else:
        out['Hora Venta'] = ''

    # Año/Mes/Semana/Día venta
    out['Año venta'] = df['fv'].dt.year.astype('Int64')
    out['Mes venta'] = df['fv'].dt.month.astype('Int64')
    out['Semana venta'] = df['fv'].dt.isocalendar().week.astype('Int64')
    out['Día semana'] = df['fv'].dt.weekday + 1  # lunes=1 ... domingo=7
    out['Hora venta'] = df.get('hora_venta_num', pd.Series([0]*len(df))).fillna(0)

    # Metricas TY (solo 2026) y LY (solo 2025)
    es_ty = df['anio'] == 2026
    for col_xlsx, col_parq, suf in [
        ('Cantidad', 'cantidad', None),
        ('Venta bruta', 'venta_bruta', None),
        ('Costo Unitario', 'costo_unitario', None),
        ('Costo Total', 'costo_total', None),
        ('Margen Front', 'margen_front', None),
        ('Comision %', 'comision_pct', None),
        ('Comisión', 'comision', None),
        ('Logística', 'logistica', None),
        ('Marketing', 'marketing', None),
    ]:
        val = pd.to_numeric(df.get(col_parq, 0), errors='coerce').fillna(0)
        out[f'{col_xlsx} TY'] = val.where(es_ty, 0)
        out[f'{col_xlsx} LY'] = val.where(~es_ty, 0)

    # Columnas 50-54: Año, Mes, Semana, Fecha Compara, Week, Obs
    out['Año'] = df['fv'].dt.year.astype('Int64')
    out['Mes'] = df['fv'].dt.month.astype('Int64')
    out['Semana'] = df['fv'].dt.isocalendar().week.astype('Int64')
    out['Fecha Compara'] = out['Fecha Comp']  # mismo valor
    out['Week'] = df['fv'].dt.isocalendar().week.astype('Int64')
    out['Obs'] = ''

    # Asegurar orden y agregar columna 56 None
    cols_final = [c for c in RAW_COLUMNS if c is not None]
    out = out[cols_final]
    return out


def generar_raw_xml(df: pd.DataFrame, tmp_dir: Path) -> bytes:
    """Genera sheet3.xml (Raw) con los datos del DataFrame usando openpyxl,
    luego extrae el XML del archivo generado."""
    tmp_xlsx = tmp_dir / '_raw_tmp.xlsx'
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('Raw')
    # Headers
    ws.append([c if c is not None else '' for c in RAW_COLUMNS])
    # Datos en chunks para no consumir tanta RAM
    n = len(df)
    print(f'   [generar_raw_xml] {n:,} filas a serializar...')
    rows = df.values.tolist()
    for r in rows:
        # Agregar None para la columna 56
        ws.append(r + [None])
    wb.save(tmp_xlsx)
    # Extraer sheet3.xml (que ahora se llama sheet1.xml en este wb chico)
    with zipfile.ZipFile(tmp_xlsx) as z:
        for n in z.namelist():
            if n.startswith('xl/worksheets/sheet'):
                return z.read(n)
    raise RuntimeError('no se encontro sheet en archivo temporal')


def construir_live():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print('[1/5] Cargando datos del parquet...')
    df_raw = cargar_raw_parquet()
    print(f'      {len(df_raw):,} filas (2025-2026)')

    print('[2/5] Generando XML de la nueva Raw...')
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        new_raw_xml = generar_raw_xml(df_raw, tmp_dir)
    print(f'      Raw XML: {len(new_raw_xml)/1024/1024:.1f} MB')

    print('[3/5] Construyendo archivo LIVE...')

    # Archivos a CONSERVAR del original (NO incluimos pivotCacheRecords3.xml:
    # lo reemplazamos por uno vacio para forzar refresh desde Raw al abrir)
    KEEP_EXACT = {
        'xl/worksheets/sheet1.xml',
        'xl/worksheets/_rels/sheet1.xml.rels',
        'xl/pivotTables/pivotTable1.xml',
        'xl/pivotTables/_rels/pivotTable1.xml.rels',
        'xl/pivotCache/pivotCacheDefinition3.xml',
        'xl/pivotCache/_rels/pivotCacheDefinition3.xml.rels',
        'xl/printerSettings/printerSettings1.bin',
        'xl/sharedStrings.xml',
        'xl/styles.xml',
        'xl/theme/theme1.xml',
        'docProps/core.xml',
        'docProps/app.xml',
        '_rels/.rels',
    }
    # Archivos a SOBRESCRIBIR / GENERAR
    # - xl/worksheets/sheet3.xml: reemplazar con new_raw_xml
    # - xl/workbook.xml: limpiar sheets y pivotCaches
    # - xl/_rels/workbook.xml.rels: limpiar referencias
    # - [Content_Types].xml: limpiar overrides
    # - xl/calcChain.xml: NO INCLUIR (Excel lo regenera)

    if OUTPUT.exists():
        OUTPUT.unlink()

    with zipfile.ZipFile(ORIGINAL, 'r') as src, \
         zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as dst:

        # 1) Copy archivos KEEP_EXACT (streaming)
        for name in sorted(src.namelist()):
            if name in KEEP_EXACT:
                with src.open(name) as fin, dst.open(name, 'w', force_zip64=True) as fout:
                    while True:
                        chunk = fin.read(1024 * 1024)
                        if not chunk:
                            break
                        fout.write(chunk)

        # 2) sheet3.xml (Raw) = nueva version del parquet
        dst.writestr('xl/worksheets/sheet3.xml', new_raw_xml)

        # 2b) pivotCacheRecords3.xml VACIO (count=0). Excel detecta cache stale
        # con refreshOnLoad=1 y la regenera desde la nueva Raw al abrir.
        empty_records = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                         '<pivotCacheRecords xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                         'count="0"/>')
        dst.writestr('xl/pivotCache/pivotCacheRecords3.xml', empty_records)

        # 3) workbook.xml: limpiar
        wb = src.read('xl/workbook.xml').decode('utf-8')
        # Eliminar sheets que no queremos
        wb = re.sub(r'<sheet name="Resumen Contri Sku Canal"[^/]+/>', '', wb)
        wb = re.sub(r'<sheet name="Resumen Ejecutivo Q1"[^/]+/>', '', wb)
        wb = re.sub(r'<sheet name="Resumen Ejecutivo S18"[^/]+/>', '', wb)
        wb = re.sub(r'<sheet name="Resumen Ejecutivo S16"[^/]+/>', '', wb)
        wb = re.sub(r'<sheet name="Base Venta Claude"[^/]+/>', '', wb)
        # Eliminar pivotCaches 1 y 2 (mantener cacheId 69 que es la de Resumen TD)
        wb = re.sub(r'<pivotCache cacheId="1"[^/]+/>', '', wb)
        wb = re.sub(r'<pivotCache cacheId="2"[^/]+/>', '', wb)
        # FilterDatabase: el original lo tiene como localSheetId="2" (Raw index 2 en
        # workbook original). Tras eliminar sheet2 (idx 1), Raw queda en idx 1.
        wb = re.sub(
            r'<definedName name="_xlnm\._FilterDatabase"[^>]*localSheetId="2"[^>]*>Raw![^<]+</definedName>',
            '<definedName name="_xlnm._FilterDatabase" localSheetId="1" hidden="1">Raw!$A$1:$BD$1</definedName>',
            wb,
        )
        dst.writestr('xl/workbook.xml', wb)

        # 4) workbook.xml.rels: limpiar
        rels = src.read('xl/_rels/workbook.xml.rels').decode('utf-8')
        for rid in ['rId2', 'rId4', 'rId5', 'rId6', 'rId7']:
            rels = re.sub(rf'<Relationship Id="{rid}"[^/]+/>', '', rels)
        rels = re.sub(r'<Relationship[^>]*pivotCacheDefinition1\.xml[^/]*/>', '', rels)
        rels = re.sub(r'<Relationship[^>]*pivotCacheDefinition2\.xml[^/]*/>', '', rels)
        rels = re.sub(r'<Relationship[^>]*calcChain\.xml[^/]*/>', '', rels)
        dst.writestr('xl/_rels/workbook.xml.rels', rels)

        # 5) [Content_Types].xml: limpiar
        ct = src.read('[Content_Types].xml').decode('utf-8')
        for sn in ['sheet2', 'sheet4', 'sheet5', 'sheet6', 'sheet7']:
            ct = re.sub(rf'<Override PartName="/xl/worksheets/{sn}\.xml"[^/]+/>', '', ct)
        for n in ['1', '2']:
            ct = re.sub(rf'<Override PartName="/xl/pivotCache/pivotCacheDefinition{n}\.xml"[^/]+/>', '', ct)
            ct = re.sub(rf'<Override PartName="/xl/pivotCache/pivotCacheRecords{n}\.xml"[^/]+/>', '', ct)
        ct = re.sub(r'<Override PartName="/xl/pivotTables/pivotTable2\.xml"[^/]+/>', '', ct)
        ct = re.sub(r'<Override PartName="/xl/pivotTables/pivotTable3\.xml"[^/]+/>', '', ct)
        ct = re.sub(r'<Override PartName="/xl/calcChain\.xml"[^/]+/>', '', ct)
        dst.writestr('[Content_Types].xml', ct)

    print('[4/5] Marcando pivot para refreshOnLoad=1...')
    # Modificar pivotCacheDefinition3.xml para que tenga refreshOnLoad=1
    _set_refresh_on_load(OUTPUT)

    print('[5/5] Validando ZIP...')
    with zipfile.ZipFile(OUTPUT) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f'ZIP invalido: {bad}')

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f'\n[OK] {OUTPUT.name}: {size_mb:.1f} MB')


def _set_refresh_on_load(xlsx_path: Path):
    """Marca refreshOnLoad=1 en pivotCacheDefinition3.xml dentro del xlsx."""
    # Leer todo el zip, modificar el contenido, reescribir
    tmp = xlsx_path.with_suffix('.tmp.xlsx')
    with zipfile.ZipFile(xlsx_path, 'r') as src, \
         zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as dst:
        for name in src.namelist():
            if name == 'xl/pivotCache/pivotCacheDefinition3.xml':
                content = src.read(name).decode('utf-8')
                # refreshOnLoad=1: Excel refresca al abrir
                if 'refreshOnLoad' in content:
                    content = re.sub(r'refreshOnLoad="\d"', 'refreshOnLoad="1"', content)
                else:
                    content = content.replace(
                        '<pivotCacheDefinition ',
                        '<pivotCacheDefinition refreshOnLoad="1" ', 1
                    )
                # recordCount=0: marca cache como vacia (combinado con records vacios fuerza rebuild)
                content = re.sub(r'recordCount="\d+"', 'recordCount="0"', content)
                dst.writestr(name, content)
            else:
                with src.open(name) as fin, dst.open(name, 'w', force_zip64=True) as fout:
                    while True:
                        chunk = fin.read(1024 * 1024)
                        if not chunk:
                            break
                        fout.write(chunk)
    shutil.move(str(tmp), str(xlsx_path))


def subir_a_drive():
    """Sube el archivo OUTPUT al Drive del user via OAuth user."""
    from drive_user_helpers import subir_o_actualizar
    file_id, link = subir_o_actualizar(
        OUTPUT, DRIVE_CARPETA_ID, NOMBRE_LIVE, hacer_publico=True
    )
    print(f'\n[drive] file_id: {file_id}')
    print(f'[drive] link:    {link}')
    return file_id, link


if __name__ == '__main__':
    construir_live()
    # Solo subir a Drive si estamos en GH Actions o si se pide explicito
    if os.environ.get('GITHUB_ACTIONS') == 'true' or '--upload' in sys.argv:
        subir_a_drive()
