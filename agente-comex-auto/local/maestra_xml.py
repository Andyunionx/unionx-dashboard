"""Cirugía XML sobre la Maestra de Importaciones (sin openpyxl al guardar).

POR QUÉ: la Maestra tiene >1.200 fórmulas de matriz dinámica (metadata.xml), un complemento de Office
(webextensions) y una tabla; openpyxl los pierde al guardar (así se dañó la copia 'Maestra Importaciones V2').
Aquí solo se reescriben las hojas que cambian; el resto del paquete queda byte a byte.
Validado el 29-sep-2026 contra la Maestra viva (vista previa revisada celda a celda).
"""
import html
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import openpyxl

PUERTO = {"SZ": "SZ", "NB": "NG", "NG": "NG", "XI": "XI", "AIR": "AIR"}   # la Maestra usa NG para Ningbo
RANGO_NUEVO = "6000"
HOJA = {"apertura_cc": "sheet1", "variables": "sheet3", "matriz": "sheet4", "resumen_var": "sheet5",
        "maestra": "sheet7", "eficiencia": "sheet8", "var_exog": "sheet9", "centros": "sheet10"}

CELL = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
F_TXT = r"(<f(?![A-Za-z])[^>]*?(?<!/)>)(.*?)(</f>)"   # fórmula con texto (no <f .../>)
ROW = re.compile(r'<row [^>]*?r="(\d+)"[^>]*?(?:/>|>.*?</row>)', re.S)


# ---------------------------------------------------------------- utilidades de celdas / referencias
def col2n(c: str) -> int:
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def n2col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def c_str(ref, texto, s=None):
    st = f' s="{s}"' if s else ""
    return f'<c r="{ref}"{st} t="inlineStr"><is><t>{esc(texto)}</t></is></c>'


def c_num(ref, v, s=None):
    st = f' s="{s}"' if s else ""
    if v is None:
        return f'<c r="{ref}"{st}/>'
    v = float(v)
    return f'<c r="{ref}"{st}><v>{int(v) if v.is_integer() else repr(v)}</v></c>'


def c_f(ref, formula, s=None, texto=False):
    st = f' s="{s}"' if s else ""
    t = ' t="str"' if texto else ""
    return f'<c r="{ref}"{st}{t}><f>{esc(formula)}</f></c>'


def serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


# referencias a OTRAS hojas (se protegen al desplazar filas de una hoja)
XREF = re.compile(r"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_\.]*)!\$?[A-Z]{1,3}\$?\d*(?::\$?[A-Z]{1,3}\$?\d*)?")
LREF = re.compile(r"(?<![A-Za-z0-9_\.\$])(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?(?![A-Za-z0-9_\(])")


def _fuera_de_comillas(texto: str, fn) -> str:
    partes = texto.split('"')
    for i in range(0, len(partes), 2):          # pares = fuera de literales de texto
        protegidos = []

        def prot(m):
            protegidos.append(m.group(0))
            return f"\x00{len(protegidos) - 1}\x00"
        seg = fn(XREF.sub(prot, partes[i]))
        partes[i] = re.sub(r"\x00(\d+)\x00", lambda m: protegidos[int(m.group(1))], seg)
    return '"'.join(partes)


def desplazar_formula(texto: str, desde: int, n: int, fin_bloque=None, fila_a=None) -> str:
    """Desplaza +n las referencias de la MISMA hoja con fila >= desde. Los rangos que terminan justo en
    fin_bloque se EXTIENDEN (incluyen las filas insertadas). fila_a=(vieja, nueva): reemplaza las
    referencias a una fila puntual (para clonar la fila modelo)."""
    def fila(r: int) -> int:
        if fila_a:
            return fila_a[1] if r == fila_a[0] else r
        return r + n if r >= desde else r

    def rep(m):
        d1, c1, d2, r1, d3, c2, d4, r2 = m.groups()
        r1 = int(r1)
        if r2 is None:
            return f"{d1}{c1}{d2}{fila(r1)}"
        r2 = int(r2)
        if not fila_a and fin_bloque is not None and r2 == fin_bloque and r1 <= fin_bloque:
            return f"{d1}{c1}{d2}{fila(r1)}:{d3}{c2}{d4}{r2 + n}"
        return f"{d1}{c1}{d2}{fila(r1)}:{d3}{c2}{d4}{fila(r2)}"
    return _fuera_de_comillas(texto, lambda seg: LREF.sub(rep, seg))


def desplazar_ref_attr(ref: str, desde: int, n: int) -> str:
    return re.sub(r"([A-Z]+)(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + n if int(m.group(2)) >= desde else m.group(2)}", ref)


def ampliar_rangos(xml: str):
    cont = [0]

    def rep(m):
        nuevo = re.sub(r"\$(3000|3062)\b", "$" + RANGO_NUEVO, m.group(2))
        cont[0] += nuevo != m.group(2)
        return m.group(1) + nuevo + m.group(3)
    return re.sub(F_TXT, rep, xml, flags=re.S), cont[0]


# ---------------------------------------------------------------- lectura de precosteos
def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def leer_precosteo(path: str) -> dict:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    kv = {str(r[0]).strip(): r[1] for r in wb["Resumen"].iter_rows(values_only=True) if r and r[0] is not None}

    def usd(clave):
        for k, v in kv.items():
            if unicodedata.normalize("NFKD", k).lower().startswith(clave):
                return _num(v) or 0.0
        return 0.0
    rows = list(wb["Productos"].iter_rows(values_only=True))
    head = [str(c).strip() if c else "" for c in rows[0]]
    iq = head.index("Qty")
    prods = [dict(zip(head, r)) for r in rows[1:] if r and r[0] is not None and _num(r[iq])]
    eta = kv.get("ETA")
    eta = eta.date() if isinstance(eta, datetime) else datetime.strptime(str(eta)[:10], "%Y-%m-%d").date()
    return {"embarque": str(kv.get("Embarque")).strip(), "puerto": PUERTO.get(str(kv.get("Puerto", "SZ"))[:2].upper(), "SZ"),
            "eta": eta, "tc": _num(kv.get("Dolar")), "pxq": usd("total amount"), "exw": usd("exw"),
            "inland_china": usd("inland china"), "flete": usd("flete"), "inland_chile": usd("inland chile"),
            "productos": prods, "archivo": Path(path).name}


# ---------------------------------------------------------------- escritura de hojas
def filas_de(xml: str) -> dict:
    return {int(m.group(1)): m.group(0) for m in ROW.finditer(xml)}


def partes_sheetdata(xml: str):
    ini, fin = xml.index("<sheetData>") + len("<sheetData>"), xml.index("</sheetData>")
    return xml[:ini], filas_de(xml[ini:fin]), xml[fin:]


def reemplazar_filas(xml: str, nuevas: dict) -> str:
    cab, filas, cola = partes_sheetdata(xml)
    filas.update(nuevas)
    return cab + "".join(filas[r] for r in sorted(filas)) + cola


def fijar_dimension(xml: str, ultima_col: str, ultima_fila: int) -> str:
    return re.sub(r'<dimension ref="[^"]+"/>', f'<dimension ref="A1:{ultima_col}{ultima_fila}"/>', xml, count=1)


def fila_maestra(r, emb, i, p) -> str:
    qty, tc = _num(p.get("Qty")), emb["tc"]
    fob_linea = (_num(p.get("EXW Producto")) or 0) + (_num(p.get("Inland China Prod")) or 0)
    sku = str(p.get("SKU") or "").strip()
    d = c_num(f"D{r}", int(sku), 1) if re.fullmatch(r"\d{1,15}", sku) else c_str(f"D{r}", sku, 1)   # convención actual
    celdas = [
        c_str(f"A{r}", emb["embarque"], 5), c_num(f"B{r}", i, 2), c_str(f"C{r}", str(p.get("Model") or "").strip(), 2), d,
        c_f(f"E{r}", f"IFERROR(VLOOKUP(Maestra!$D{r},BASE!A:B,2,FALSE),0)", 1, texto=True),
        c_num(f"F{r}", qty, 2), c_num(f"G{r}", _num(p.get("Price")), 10), c_f(f"H{r}", f"F{r}*G{r}", 29),
        f'<c r="I{r}" s="29"/>', c_num(f"J{r}", fob_linea / qty if qty else None, 1), c_num(f"K{r}", fob_linea, 1),
        c_num(f"L{r}", _num(p.get("Flete Prod")), 1), c_f(f"M{r}", f"K{r}+L{r}", 1), c_f(f"N{r}", f"M{r}*{tc}", 1),
        f'<c r="O{r}" s="1"/>', f'<c r="P{r}" s="1"/>', c_f(f"Q{r}", f"N{r}+P{r}", 1),
        c_num(f"R{r}", (_num(p.get("Inland Chile Prod")) or 0) * tc, 1), c_f(f"S{r}", f"T{r}*F{r}", 1),
        c_num(f"T{r}", _num(p.get("Costo Internado Unit (CLP)")), 56),
        c_f(f"U{r}", f"IFERROR(VLOOKUP(Maestra!$D{r},BASE!A:N,14,FALSE),0)", 31),
        c_f(f"V{r}", f"IFERROR(VLOOKUP(Maestra!$D{r},BASE!A:P,16,FALSE),0)", 43),
        c_f(f"W{r}", f"IFERROR((U{r}+V{r})-(G{r}+I{r}),0)", 10), c_f(f"X{r}", f"IFERROR(W{r}/(U{r}+V{r}),0)", 33),
        c_f(f"Y{r}", f"W{r}*F{r}", 2), c_f(f"Z{r}", f"IFERROR(VLOOKUP(A{r},'Variacion Exog.'!A:B,2,FALSE),0)", 2),
        c_f(f"AA{r}", f"IFERROR(VLOOKUP(A{r},'Apertura Centros de Costo'!B:H,7,FALSE),0)", 33),
        c_f(f"AB{r}", f"+IFERROR(VLOOKUP(Maestra!$A{r},'Apertura Centros de Costo'!$B$2:$K$1000,10,FALSE),\"\")", 33, texto=True),
        c_f(f"AC{r}", f"IFERROR(AVERAGEIF(Maestra!$D$2:$D$4670,Maestra!$D{r},Maestra!$T$2:$T$4670),0)", 1),
        c_f(f"AD{r}", f"_xlfn.MAXIFS(Maestra!$T$2:$T$4670,Maestra!$D$2:$D$4670,Maestra!$D{r})", 1),
        c_f(f"AE{r}", f"_xlfn.MINIFS(Maestra!$T$2:$T$4670,Maestra!$D$2:$D$4670,Maestra!$D{r})", 1),
        c_num(f"AF{r}", emb["eta"].year, 34), c_num(f"AG{r}", serial(emb["eta"]), 35),
    ]
    return f'<row r="{r}" spans="1:33" ht="14.25" customHeight="1">' + "".join(celdas) + "</row>"


def _ajustar_fila(row_xml: str, fn_formula, fn_refattr, nueva_r=None) -> str:
    if nueva_r is not None:
        row_xml = re.sub(r'^<row ([^>]*?)r="\d+"', lambda m: f'<row {m.group(1)}r="{nueva_r}"', row_xml)
        row_xml = re.sub(r'<c r="([A-Z]+)\d+"', lambda m: f'<c r="{m.group(1)}{nueva_r}"', row_xml)
    row_xml = re.sub(r"<f(?![A-Za-z])([^>]*?)(/?)>", lambda m: "<f" + re.sub(r'ref="([^"]+)"', lambda a: f'ref="{fn_refattr(a.group(1))}"', m.group(1)) + m.group(2) + ">", row_xml)
    return re.sub(F_TXT, lambda m: m.group(1) + esc(fn_formula(html.unescape(m.group(2)))) + m.group(3), row_xml, flags=re.S)


def insertar_en_listado(xml, fin_bloque, fila_modelo, embs, codigo_modelo, puerto_modelo, anio_modelo):
    """Inserta len(embs) filas después de fin_bloque clonando fila_modelo; desplaza todo lo de abajo."""
    n, desde = len(embs), fin_bloque + 1
    cab, filas, cola = partes_sheetdata(xml)
    modelo = filas[fila_modelo]
    nuevas = {}
    for r, rx in filas.items():
        nr = r + n if r >= desde else r
        nuevas[nr] = _ajustar_fila(rx, lambda t: desplazar_formula(t, desde, n, fin_bloque),
                                   lambda a: desplazar_ref_attr(a, desde, n), nr if nr != r else None)
    for i, e in enumerate(embs):
        r = desde + i

        def fn(t, r=r, e=e):
            t = t.replace(f'"{codigo_modelo}"', f'"{e["embarque"]}"').replace(f'"{puerto_modelo}"', f'"{e["puerto"]}"')
            t = re.sub(rf"(?<![0-9]){anio_modelo}(?![0-9])", str(e["eta"].year), t)
            return desplazar_formula(t, 0, 0, fila_a=(fila_modelo, r))
        nuevas[r] = re.sub(r"<v>.*?</v>", "", _ajustar_fila(modelo, fn, lambda a, r=r: re.sub(r"\d+", str(r), a), r), flags=re.S)
    cola = re.sub(r'((?:sqref|ref)=")([^"]+)(")',
                  lambda m: m.group(1) + " ".join(desplazar_ref_attr(x, desde, n) for x in m.group(2).split()) + m.group(3), cola)
    xml = cab + "".join(nuevas[r] for r in sorted(nuevas)) + cola
    dim = re.search(r'<dimension ref="A1:([A-Z]+)(\d+)"/>', xml)
    return fijar_dimension(xml, dim.group(1), int(dim.group(2)) + n)


def actualizar_matriz(xml: str, embs: list, ss: list):
    cab, filas, cola = partes_sheetdata(xml)
    ult_col = max(col2n(c) for c, r, a, inner in CELL.findall(filas[5]))
    cols = [n2col(ult_col + 1 + i) for i in range(len(embs))]
    todas = [n2col(i) for i in range(3, ult_col + 1)] + cols

    def formula(col, r):
        return (f"IFERROR(AVERAGEIFS(Maestra!$T$2:$T${RANGO_NUEVO},Maestra!$D$2:$D${RANGO_NUEVO},$A{r},"
                f"Maestra!$A$2:$A${RANGO_NUEVO},{col}$5),\"\")")
    filas[5] = filas[5].replace("</row>", "".join(c_str(f"{c}5", e["embarque"], 252) for c, e in zip(cols, embs)) + "</row>")
    existentes = set()
    for r in [r for r in filas if r >= 6]:
        m = re.search(rf'<c r="A{r}"([^>]*?)(?:/>|>(.*?)</c>)', filas[r], flags=re.S)
        if m and m.group(2):
            v = valor_literal(m.group(1), m.group(2), ss)
            if v is not None:
                existentes.add(v)
            filas[r] = filas[r].replace("</row>", "".join(c_f(f"{c}{r}", formula(c, r), 210, texto=True) for c in cols) + "</row>")
    r_sig = max(filas) + 1
    nuevos = []
    for e in embs:
        for p in e["productos"]:
            sku = str(p.get("SKU") or "").strip()
            if sku and sku not in existentes and sku not in [s for s, _ in nuevos]:
                nuevos.append((sku, str(p.get("Descripcion") or "").split("\n")[0].strip()[:80]))
    for sku, nombre in nuevos:
        filas[r_sig] = (f'<row r="{r_sig}">' + c_str(f"A{r_sig}", sku) + c_str(f"B{r_sig}", nombre)
                        + "".join(c_f(f"{c}{r_sig}", formula(c, r_sig), 210, texto=True) for c in todas) + "</row>")
        r_sig += 1
    xml = cab + "".join(filas[r] for r in sorted(filas)) + cola
    xml = re.sub(r'(<conditionalFormatting[^>]*sqref=")C6:[A-Z]+\d+(")', rf"\g<1>C6:{cols[-1]}{r_sig - 1}\g<2>", xml)
    return fijar_dimension(xml, cols[-1], r_sig - 1), len(cols), len(nuevos)


# ---------------------------------------------------------------- lectura robusta (corridas sucesivas)
# Las filas que agrega este módulo usan texto en línea (inlineStr), no la tabla de textos compartidos:
# toda lectura de "¿qué hay en la celda?" debe entender los dos formatos, o la corrida siguiente
# no vería lo que agregó la anterior (duplicaría embarques o escribiría encima).
def valor_literal(attrs: str, inner: str, ss: list):
    """Valor escrito (no fórmula) de una celda: texto compartido, texto en línea o número. None si no hay."""
    if not inner or "<f" in inner:
        return None
    if 't="s"' in attrs:
        v = re.search(r"<v>(\d+)</v>", inner)
        return ss[int(v.group(1))].strip() if v else None
    if 't="inlineStr"' in attrs:
        t = re.findall(r"<t[^>]*>(.*?)</t>", inner, flags=re.S)
        return html.unescape("".join(t)).strip() if t else None
    v = re.search(r"<v>(.*?)</v>", inner, flags=re.S)
    return v.group(1).strip() if v else None


def literales_columna(xml: str, col: str, ss: list) -> dict:
    """{fila: valor} de los valores escritos en una columna."""
    out = {}
    for c, r, attrs, inner in CELL.findall(xml):
        if c == col:
            v = valor_literal(attrs, inner, ss)
            if v not in (None, ""):
                out[int(r)] = v
    return out


RX_COD = re.compile(r'"(\d{2}[A-Z]{2}\d{4}[A-Z]*)"')
RX_PTO = re.compile(r'\$D\$4="(SZ|NG|XI|AIR)"')
RX_ANIO = re.compile(r"\$B\$4=(\d{4}|0)\b")


def detectar_listado(path, hoja: str) -> dict:
    """Bloque de filas por embarque de un listado ('1. Apertura CC' / '3. Variables Exógenas'):
    fin = última fila con código de embarque en sus fórmulas; modelo = última fila 'normal' (marítima,
    con año) para clonar. Hoy: Apertura CC fin 117 / modelo 117; Variables fin 115 (24TP0109 AIR) / modelo 114."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    filas = []
    for i, row in enumerate(wb[hoja].iter_rows(min_row=1, max_col=6, values_only=True), 1):
        txt = " ".join(str(c) for c in row if isinstance(c, str) and c.startswith("="))
        cod = RX_COD.search(txt)
        if cod:
            pto, anio = RX_PTO.search(txt), RX_ANIO.search(txt)
            filas.append((i, cod.group(1), pto.group(1) if pto else None, int(anio.group(1)) if anio else None))
    wb.close()
    if not filas:
        raise RuntimeError(f"No encontré el listado de embarques en '{hoja}'")
    fin = max(f[0] for f in filas)
    normales = [f for f in filas if f[2] in ("SZ", "NG") and f[3] and f[3] >= 2000]
    r, cod, pto, anio = max(normales)
    return {"fin": fin, "modelo": r, "codigo": cod, "puerto": pto, "anio": anio}


def embarques_en_maestra(path) -> set:
    z = __import__("zipfile").ZipFile(path)
    ss = textos_compartidos(z)
    return set(literales_columna(z.read(f"xl/worksheets/{HOJA['maestra']}.xml").decode("utf-8"), "A", ss).values())


def textos_compartidos(z) -> list:
    return [html.unescape(re.sub(r"<[^>]+>", "", x))
            for x in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8"), flags=re.S)]


# ---------------------------------------------------------------- construcción completa
def construir(maestra_path: Path, embs: list, destino: Path) -> dict:
    """Escribe en `destino` la Maestra con los embarques `embs` (dicts de leer_precosteo) agregados."""
    import zipfile
    from xml.etree import ElementTree
    z = zipfile.ZipFile(maestra_path)
    xmls = {k: z.read(f"xl/worksheets/{v}.xml").decode("utf-8") for k, v in HOJA.items()}
    ss = textos_compartidos(z)

    # Maestra: filas por SKU desde la fila siguiente a la última con N° de embarque escrito
    col_a = literales_columna(xmls["maestra"], "A", ss)
    ya = set(col_a.values())
    dup = [e["embarque"] for e in embs if e["embarque"] in ya]
    if dup:
        raise RuntimeError(f"Embarques que ya están en la Maestra: {dup}")
    r = max(col_a) + 1
    if r + sum(len(e["productos"]) for e in embs) > int(RANGO_NUEVO) - 100:
        raise RuntimeError(f"La Maestra se acerca a la fila {RANGO_NUEVO}: hay que ampliar los rangos antes de seguir")
    fila_ini, nuevas = r, {}
    for e in embs:
        for i, p in enumerate(e["productos"], start=1):
            nuevas[r] = fila_maestra(r, e, i, p)
            r += 1
    ult_fila = max(max(filas_de(xmls["maestra"])), r - 1)
    xmls["maestra"] = fijar_dimension(reemplazar_filas(xmls["maestra"], nuevas), "AG", ult_fila)

    # Variacion Exog. / Eficiencia / Apertura Centros de Costo: 1 fila por embarque
    rv = max(literales_columna(xmls["var_exog"], "A", ss)) + 1
    rf = max(literales_columna(xmls["eficiencia"], "A", ss)) + 1
    rc = max(literales_columna(xmls["centros"], "B", ss)) + 1
    nv, ne, nc = {}, {}, {}
    for k, e in enumerate(embs):
        x, y, w = rv + k, rf + k, rc + k
        nv[x] = (f'<row r="{x}">' + c_str(f"A{x}", e["embarque"], 2) + c_num(f"B{x}", e["tc"], 2) + c_num(f"C{x}", e["flete"], 30)
                 + c_num(f"D{x}", e["pxq"], 30) + c_f(f"E{x}", f"C{x}/D{x}", 105) + c_str(f"F{x}", e["puerto"], 64) + "</row>")
        ne[y] = (f'<row r="{y}">' + c_str(f"A{y}", e["embarque"], 2)
                 + c_f(f"B{y}", f"VLOOKUP(A{y},'Variacion Exog.'!A:F,6,0)", 82, texto=True)
                 + c_f(f"C{y}", f"VLOOKUP($A{y},Maestra!$A$2:$Z${RANGO_NUEVO},26,0)", 82)
                 + c_f(f"D{y}", f"SUMIF(Maestra!$A:$A,$A{y},Maestra!H:H)", 82) + c_f(f"E{y}", f"SUMIF(Maestra!$A:$A,$A{y},Maestra!K:K)", 82)
                 + c_f(f"F{y}", f"SUMIF(Maestra!$A:$A,$A{y},Maestra!M:M)", 82) + c_f(f"G{y}", f"SUMIF(Maestra!$A:$A,$A{y},Maestra!S:S)/C{y}", 82)
                 + c_f(f"H{y}", f"E{y}/$D{y}-1", 83) + c_f(f"I{y}", f"F{y}/$D{y}-1", 83) + c_f(f"J{y}", f"G{y}/$D{y}-1", 83)
                 + f'<c r="K{y}" s="84"/>' + c_f(f"L{y}", f"VLOOKUP(A{y},Maestra!A:AG,33,0)", 84) + c_num(f"M{y}", e["eta"].year, 5) + "</row>")
        tot = e["pxq"] + e["exw"] + e["inland_china"] + e["flete"] + e["inland_chile"]
        nc[w] = (f'<row r="{w}">' + c_num(f"A{w}", e["eta"].year, 154) + c_str(f"B{w}", e["embarque"], 94)
                 + "".join(c_num(f"{col}{w}", v / tot if tot else None, 128)
                           for col, v in zip("CDEFG", (e["pxq"], e["exw"], e["inland_china"], e["flete"], e["inland_chile"])))
                 + c_f(f"H{w}", f"SUM(D{w}:G{w})", 128)
                 + c_f(f"I{w}", f"IFERROR(VLOOKUP(B{w},'Eficiencia Importación'!$A$2:$G$999,7,0),0)", 123)
                 + c_f(f"J{w}", f"+I{w}*H{w}", 156) + c_f(f"K{w}", f"VLOOKUP(B{w},'Variacion Exog.'!A:F,6,0)", 146, texto=True)
                 + f'<c r="L{w}" s="150"/>' + "</row>")
    xmls["var_exog"] = reemplazar_filas(xmls["var_exog"], nv)
    xmls["eficiencia"] = reemplazar_filas(xmls["eficiencia"], ne)
    xmls["centros"] = reemplazar_filas(xmls["centros"], nc)

    # listados por embarque (insertan filas y desplazan lo de abajo)
    la = detectar_listado(maestra_path, "1. Apertura CC")
    lv = detectar_listado(maestra_path, "3. Variables Exógenas")
    xmls["apertura_cc"] = insertar_en_listado(xmls["apertura_cc"], la["fin"], la["modelo"], embs, la["codigo"], la["puerto"], la["anio"])
    xmls["variables"] = insertar_en_listado(xmls["variables"], lv["fin"], lv["modelo"], embs, lv["codigo"], lv["puerto"], lv["anio"])
    xmls["matriz"], n_cols, n_skus = actualizar_matriz(xmls["matriz"], embs, ss)

    total_amp = 0
    for k in ("apertura_cc", "variables", "matriz", "resumen_var", "eficiencia"):
        xmls[k], nn = ampliar_rangos(xmls[k])
        total_amp += nn

    destino.parent.mkdir(parents=True, exist_ok=True)
    reemplazo = {f"xl/worksheets/{v}.xml": xmls[k] for k, v in HOJA.items()}
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as out:
        for item in z.infolist():
            if item.filename == "xl/calcChain.xml":
                continue
            data = z.read(item.filename)
            if item.filename in reemplazo:
                data = reemplazo[item.filename].encode("utf-8")
            elif item.filename == "xl/workbook.xml":
                t = data.decode("utf-8")
                t = re.sub(r"<calcPr([^>]*?)/>",
                           lambda m: "<calcPr" + re.sub(r'\s*fullCalcOnLoad="\d"', "", m.group(1)) + ' fullCalcOnLoad="1"/>', t, count=1)
                data = t.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                data = re.sub(rb'<Override[^>]*PartName="/xl/calcChain.xml"[^>]*/>', b"", data)
            elif item.filename == "xl/_rels/workbook.xml.rels":
                data = re.sub(rb'<Relationship[^>]*Target="calcChain.xml"[^>]*/>', b"", data)
            out.writestr(item, data)

    # validación: XML bien formado, openpyxl abre, y lo nuevo se lee de vuelta donde corresponde
    zp = zipfile.ZipFile(destino)
    for nombre in reemplazo:
        ElementTree.fromstring(zp.read(nombre))
    wb = openpyxl.load_workbook(destino, read_only=True)
    n_hojas = len(wb.sheetnames)
    wb.close()
    ss2 = textos_compartidos(zp)
    leidos = set(literales_columna(zp.read(f"xl/worksheets/{HOJA['maestra']}.xml").decode("utf-8"), "A", ss2).values())
    faltan = [e["embarque"] for e in embs if e["embarque"] not in leidos]
    if faltan:
        raise RuntimeError(f"Validación: no se leen de vuelta en Maestra {faltan}")
    return {"filas_maestra": len(nuevas), "fila_ini": fila_ini, "fila_fin": r - 1, "embarques": len(embs),
            "matriz_columnas": n_cols, "matriz_skus": n_skus, "formulas_ampliadas": total_amp, "hojas": n_hojas,
            "listado_apertura": la, "listado_variables": lv}


