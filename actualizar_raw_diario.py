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
# Plantilla original (172 MB) en Drive. Gitignored por tamano -> en GitHub
# Actions no existe en el checkout, se baja de aca. file_id permanente.
PLANTILLA_DRIVE_ID = '1txNWM21b2czKGhWL-FD6VigXk-QyqZ_D'
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
    """Lee parquet (hist + mes_actual), filtra a 2025-2026, prepara 56 cols.

    CRITICAL: mes_actual se filtra a >= CUTOFF_HISTORICO. El historico tiene
    foto fija que ya incluye 31-may y 1-jun; sin el filtro esos dias se
    cuentan DOS veces (bug $647M vs $538M en pivot LIVE, 11-jun-2026).
    """
    cutoff = '2026-06-02'
    try:
        shared_path = PROJECT_ROOT / 'views' / 'shared.py'
        if shared_path.exists():
            for line in shared_path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('CUTOFF_HISTORICO'):
                    val = line.split('=', 1)[1].strip().split('#')[0].strip().strip("'\"")
                    if len(val) == 10 and val[4] == '-':
                        cutoff = val
                    break
    except Exception:
        pass

    h = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_historico.parquet')
    m = pd.read_parquet(PROJECT_ROOT / 'data' / 'historico' / 'ventas_mes_actual.parquet')
    m_fv = pd.to_datetime(m['fecha_venta'], errors='coerce').dt.strftime('%Y-%m-%d')
    m = m[m_fv >= cutoff].copy()
    cols = [c for c in m.columns if c in h.columns]
    df = pd.concat([h[cols], m[cols]], ignore_index=True)

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
    # Generador (no df.values.tolist()) para no duplicar 440k filas en RAM.
    for r in df.itertuples(index=False, name=None):
        # Agregar None para la columna 56
        ws.append(list(r) + [None])
    del df
    import gc
    gc.collect()
    wb.save(tmp_xlsx)
    # Extraer sheet3.xml (que ahora se llama sheet1.xml en este wb chico)
    with zipfile.ZipFile(tmp_xlsx) as z:
        for n in z.namelist():
            if n.startswith('xl/worksheets/sheet'):
                return z.read(n)
    raise RuntimeError('no se encontro sheet en archivo temporal')


def _asegurar_plantilla():
    """Si la plantilla original no existe (caso GitHub Actions, porque pesa
    172 MB y esta gitignored), la baja de Drive por su file_id. En local no
    hace nada (la plantilla ya esta en disco)."""
    if ORIGINAL.exists():
        return
    print(f'[plantilla] no existe local -> bajando de Drive ({PLANTILLA_DRIVE_ID})...', flush=True)
    from drive_user_helpers import descargar_archivo
    descargar_archivo(PLANTILLA_DRIVE_ID, ORIGINAL)


def construir_live():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _asegurar_plantilla()

    print('[1/5] Cargando datos del parquet...')
    print('[2/5] Generando XML de la nueva Raw...')
    # No retener el df fuera de generar_raw_xml: asi su unica referencia es el
    # parametro y se libera (del+gc) antes del zip-surgery, evitando OOM.
    with tempfile.TemporaryDirectory() as tmp:
        new_raw_xml = generar_raw_xml(cargar_raw_parquet(), Path(tmp))
    print(f'      Raw XML: {len(new_raw_xml)/1024/1024:.1f} MB')

    print('[3/5] Construyendo archivo LIVE...')

    # Reorden de FILAS de la TD: Mes > Week > Tipo Negocio > Canal > Marca >
    # Cat.padre > Cat.hijo > Producto > SKU. "Fecha Compara" (idx 52) pasa de
    # FILA a FILTRO (page), junto a Proveedor/Tipo Marca/etc (pedido Nicolás).
    # Idx = posicion del campo en la cache. Ver Reporte Ventas Empresa New.xlsx.
    _TD_ROWFIELDS = ('<rowFields count="9"><field x="50"/><field x="53"/><field x="23"/>'
                     '<field x="9"/><field x="19"/><field x="14"/><field x="15"/>'
                     '<field x="12"/><field x="8"/></rowFields>')

    def _patch_td_rowfields(xml):
        # Fecha Compara (idx 52): de FILA a FILTRO -> axisRow pasa a axisPage
        pf = list(re.finditer(r'<pivotField\b[^>]*?/>|<pivotField\b[^>]*?>.*?</pivotField>', xml, re.S))
        if len(pf) > 52 and 'axis="axisRow"' in pf[52].group(0):
            s, e = pf[52].span()
            xml = xml[:s] + pf[52].group(0).replace('axis="axisRow"', 'axis="axisPage"', 1) + xml[e:]
        # filas: nuevo orden (sin Fecha Compara)
        xml = re.sub(r'<rowFields[^>]*>.*?</rowFields>', _TD_ROWFIELDS, xml, count=1, flags=re.S)
        # filtros (page): agregar Fecha Compara (fld 52) si no esta
        m = re.search(r'<pageFields count="(\d+)">(.*?)</pageFields>', xml, re.S)
        if m and 'fld="52"' not in m.group(2):
            n = int(m.group(1)) + 1
            xml = (xml[:m.start()] + f'<pageFields count="{n}">{m.group(2)}'
                   '<pageField fld="52" hier="-1"/></pageFields>' + xml[m.end():])
        return xml

    def _patch_td_datafields(xml):
        # Agrega Comisión/Logística/Marketing TY como campos de Valores ($, suma).
        # fld 37/38/39 = cacheFields Comisión/Logística/Marketing TY. Idempotente.
        nuevos = ('<dataField name=" Comisión $ TY" fld="37" baseField="23" baseItem="1" numFmtId="3"/>'
                  '<dataField name=" Logística $ TY" fld="38" baseField="23" baseItem="1" numFmtId="3"/>'
                  '<dataField name=" Marketing $ TY" fld="39" baseField="23" baseItem="1" numFmtId="3"/>')
        m = re.search(r'<dataFields count="(\d+)">(.*?)</dataFields>', xml, re.S)
        if m and 'fld="37"' not in m.group(2):
            n = int(m.group(1)) + 3
            xml = xml[:m.start()] + f'<dataFields count="{n}">{m.group(2)}{nuevos}</dataFields>' + xml[m.end():]
        # marcar los pivotField 37/38/39 como dataField (mismo patrón que fld 31/32)
        for idx in (39, 38, 37):   # alto->bajo para no invalidar spans
            pf = list(re.finditer(r'<pivotField\b[^>]*?/>|<pivotField\b[^>]*?>.*?</pivotField>', xml, re.S))
            g = pf[idx].group(0)
            if 'dataField=' not in g:
                s, e = pf[idx].span()
                xml = xml[:s] + g.replace('<pivotField ', '<pivotField dataField="1" ', 1) + xml[e:]
        # extender 3 columnas el rango del pivot (Excel lo recalcula al refrescar igual)
        xml = xml.replace('ref="B8:Y22"', 'ref="B8:AB22"', 1)
        return xml

    def _limpiar_resumen_td(xml):
        # Quita filas 1-2 de "Resumen TD": datos sueltos (fechas/%) de scratch que
        # quedaron en la plantilla, ARRIBA del pivot (B8:Y22). No tocan el pivot.
        for r in ('1', '2'):
            xml = re.sub(rf'<row r="{r}"[^>]*?/>', '', xml, count=1)
            xml = re.sub(rf'<row r="{r}"[^>]*?>.*?</row>', '', xml, count=1, flags=re.S)
        return xml

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

        # 1) Copy archivos KEEP_EXACT (streaming). pivotTable1.xml se parcha
        #    para reordenar las FILAS de la TD (orden pedido por Nicolás/Andrés).
        for name in sorted(src.namelist()):
            if name == 'xl/pivotTables/pivotTable1.xml':
                dst.writestr(name, _patch_td_datafields(_patch_td_rowfields(src.read(name).decode('utf-8'))))
            elif name == 'xl/worksheets/sheet1.xml':
                dst.writestr(name, _limpiar_resumen_td(src.read(name).decode('utf-8')))
            elif name in KEEP_EXACT:
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
