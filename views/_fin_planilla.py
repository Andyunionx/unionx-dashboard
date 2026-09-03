"""
Dominio Planificación Financiera 2026 — una sola fuente de verdad.

Lee los parquets generados por extract_finanzas_planificacion.py (vía _fin_data)
y entrega estructuras limpias para las vistas de la app y los reportes:
  - P&L / EERR (fuente: Fcst EERR — el resultado validado en los reportes)
  - Balance (EEFF)
  - Ratios financieros (EEFF filas 138-157)
  - Deuda financiera + composición + cuotas
  - Capital de Trabajo (KT) + existencias

Convención de unidades de salida: **MM CLP** (millones) para montos; ratios/meses
tal cual. Las hojas de balance vienen en miles (÷1000) y el P&L en CLP crudo (÷1e6).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

try:
    from views import _fin_data as D
except ImportError:  # ejecución standalone
    import _fin_data as D

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def label_mes(year: int, month: int) -> str:
    return f"{MESES[month - 1]}-{str(year)[2:]}"


def _periodos(df) -> list[tuple[int, int]]:
    if df is None or df.empty or "year" not in df.columns:
        return []
    p = df[["year", "month"]].drop_duplicates().sort_values(["year", "month"])
    return [(int(y), int(m)) for y, m in p.itertuples(index=False)]


def ultimo_mes_real(periodos: list[tuple[int, int]]) -> tuple[int, int]:
    """Último período con resultado REAL = mes en curso − 1 (el resto es forecast).
    Se acota a los períodos disponibles. Regla de Andrés: 'siempre un mes -1'.
    """
    if not periodos:
        return (None, None)
    t = date.today()
    corte = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    candidatos = [p for p in periodos if p <= corte]
    return max(candidatos) if candidatos else max(periodos)


def _first(sub, col, linea, exact=True):
    if exact:
        s = sub[sub["linea"] == linea][col]
    else:
        s = sub[sub["linea"].astype(str).str.startswith(linea)][col]
    return float(s.iloc[0]) if len(s) else None


# ============================================================
# P&L / EERR  (fuente: Fcst EERR)
# ============================================================
PL_MAP = {
    "venta": "Ingreso de Explotación",
    "costo": "Costo de Explotación",
    "mg_explot": "Margen de Explotación",
    "mg_contrib": "Margen de Contribución",
    "gav": "TOTAL GAV",
    "ebit": "RESULTADO OPERACIONAL",
    "rno": "Resultado No Operacional",
    "utilidad": "Utilidad del Ejercicio",
    "ebitda": "EBITDA",
}
# orden de la cascada para tablas
PL_ORDEN = [
    ("venta", "Ingreso de explotación (venta)", False),
    ("costo", "Costo de explotación", False),
    ("mg_explot", "Margen de explotación", True),
    ("comisiones", "(−) Comisiones + costos variables", False),
    ("mg_contrib", "Margen de contribución", True),
    ("gav", "(−) GAV", False),
    ("ebit", "Resultado operacional (EBIT)", True),
    ("rno", "(−) Resultado no operacional", False),
    ("ebitda", "EBITDA", True),
    ("utilidad", "Utilidad del ejercicio", True),
]


def pl_source() -> pd.DataFrame:
    return D.fcst_eerr()


def pl_periodos() -> list[tuple[int, int]]:
    return _periodos(pl_source())


def _pl_from(sub) -> dict:
    out = {}
    for k, label in PL_MAP.items():
        s = sub[sub["linea"] == label]["valor_fcst"]
        out[k] = float(s.sum()) / 1e6 if len(s) else None
    if out.get("mg_explot") is not None and out.get("mg_contrib") is not None:
        # comisiones + variables (lo que separa margen bruto de contribución)
        out["comisiones"] = -abs(out["mg_explot"] - out["mg_contrib"])
    else:
        out["comisiones"] = None
    # GAV viene con signo inconsistente entre años en la planilla
    # (2025 negativo, 2026 positivo) → normalizar a magnitud positiva
    if out.get("gav") is not None:
        out["gav"] = abs(out["gav"])
    return out


def pl_mes(year: int, month: int) -> dict:
    df = pl_source()
    return _pl_from(df[(df["year"] == year) & (df["month"] == month)])


def pl_rango(year: int, m1: int, m2: int) -> dict:
    df = pl_source()
    return _pl_from(df[(df["year"] == year) & (df["month"] >= m1) & (df["month"] <= m2)])


def pl_mensual_series(year: int) -> dict:
    """Serie mensual del año: {mes: {venta, mc, mc_pct}} en MM CLP (real + forecast)."""
    df = pl_source()
    sub = df[df["year"] == year]
    out = {}
    for m in sorted(sub["month"].unique()):
        s = sub[sub["month"] == m]
        venta = float(s[s["linea"] == PL_MAP["venta"]]["valor_fcst"].sum()) / 1e6
        mc = float(s[s["linea"] == PL_MAP["mg_contrib"]]["valor_fcst"].sum()) / 1e6
        out[int(m)] = {"venta": venta or None, "mc": mc,
                       "mc_pct": (mc / venta * 100) if venta else None}
    return out


# Presupuesto / metas (hoja Metas 2026) — para el comparativo YTD vs Ppto
META_KPI = {"venta": "Venta", "mg_contrib": "Contribución", "gav": "GAV",
            "ebitda": "EBITDA", "utilidad": "Utilidad"}


def presupuesto_ytd(year: int, mes: int, tipo: str = "Meta") -> dict:
    """Acumulado ene→mes de la hoja Metas 2026 por KPI. tipo: Meta | Resultado | Resultado 2025."""
    df = D.metas_2026()
    if df is None or df.empty:
        return {}
    sub = df[(df["year"] == year) & (df["month"] <= mes) & (df["tipo"] == tipo)]
    out = {}
    for k, kpi in META_KPI.items():
        s = sub[sub["kpi"] == kpi]["valor"]
        out[k] = float(s.sum()) / 1e6 if len(s) else None
    return out


METAS_KPIS = ["Venta", "Contribución", "GAV", "EBITDA", "Utilidad"]


def metas_periodos() -> list[tuple[int, int]]:
    return _periodos(D.metas_2026())


def metas_resumen(year: int, mes: int, acumulado: bool = True) -> dict:
    """Meta vs Resultado vs 2025 por KPI (mes puntual o acumulado ene→mes), en MM."""
    df = D.metas_2026()
    if df is None or df.empty:
        return {}
    if acumulado:
        sub = df[(df["year"] == year) & (df["month"] <= mes)]
    else:
        sub = df[(df["year"] == year) & (df["month"] == mes)]
    out = {}
    for kpi in METAS_KPIS:
        s = sub[sub["kpi"] == kpi]
        out[kpi] = {t: (float(s[s["tipo"] == t]["valor"].sum()) / 1e6 if len(s[s["tipo"] == t]) else None)
                    for t in ["Meta", "Resultado", "Resultado 2025"]}
    return out


# ============================================================
# Presupuesto operacional (P&L Drive — control_gestion / Sheet Gabriela)
# ============================================================
DRIVE_KPI = {"venta": "VENTA", "contribucion": "CONTRIB", "gav": "GASTO"}


def drive_periodos() -> list[tuple[int, int]]:
    return _periodos(D.control_gestion())


def drive_pl(year: int, mes: int, acumulado: bool = True) -> dict:
    """P&L Real (FCST) vs Presupuesto (PPTO) del P&L Drive, en MM. EBIT = Contrib + GAV."""
    df = D.control_gestion()
    if df is None or df.empty:
        return {}
    sub = df[(df["year"] == year) & (df["month"] <= mes)] if acumulado else df[(df["year"] == year) & (df["month"] == mes)]
    out = {}
    for k, kpi in DRIVE_KPI.items():
        s = sub[sub["kpi"] == kpi]
        out[k] = {"ppto": float(s[s["escenario"] == "PPTO"]["valor"].sum()) / 1000,
                  "real": float(s[s["escenario"] == "FCST"]["valor"].sum()) / 1000}
    out["ebit"] = {e: out["contribucion"][e] + out["gav"][e] for e in ("ppto", "real")}
    return out


def drive_gasto(year: int, mes: int, acumulado: bool = True, by=("linea_negocio", "area")) -> pd.DataFrame:
    """Gasto (GAV) Presupuesto vs Real por dimensión; Δ positivo = bajo presupuesto (ahorro)."""
    df = D.control_gestion()
    if df is None or df.empty:
        return pd.DataFrame()
    g = df[(df["year"] == year) & (df["kpi"] == "GASTO")]
    g = g[g["month"] <= mes] if acumulado else g[g["month"] == mes]
    by = list(by)
    p = (g[g["escenario"] == "PPTO"].groupby(by)["valor"].sum() / 1000).abs()
    r = (g[g["escenario"] == "FCST"].groupby(by)["valor"].sum() / 1000).abs()
    t = pd.DataFrame({"Ppto": p, "Real": r}).fillna(0)
    t["ahorro"] = t["Ppto"] - t["Real"]          # + = gastó menos que presupuesto
    t["pct"] = (t["Real"] / t["Ppto"] - 1) * 100  # desvío %
    return t[t.Ppto + t.Real > 1].reset_index().sort_values("ahorro")


def metas_grid(kpi: str, year: int) -> pd.DataFrame:
    """Grilla mensual de un KPI tal como en la hoja Metas 2026:
    filas = tipo (Meta / Resultado / Var % / Resultado 2025 / Variación %), columnas = meses.
    """
    df = D.metas_2026()
    if df is None or df.empty:
        return pd.DataFrame()
    sub = df[(df["kpi"] == kpi) & (df["year"] == year)]
    if sub.empty:
        return pd.DataFrame()
    piv = sub.pivot_table(index="tipo", columns="month", values="valor", aggfunc="first")
    return piv


def metas_serie(kpi: str, tipo: str, year: int) -> dict:
    """Serie mensual {month: valor MM} de un KPI/tipo, para gráficos de evolución."""
    df = D.metas_2026()
    if df is None or df.empty:
        return {}
    sub = df[(df["year"] == year) & (df["kpi"] == kpi) & (df["tipo"] == tipo)]
    return {int(m): float(v) / 1e6 for m, v in zip(sub["month"], sub["valor"])}


# EERR anual (fuente: hoja P&L / pyl_mensual) — base correcta para "P&L Bancos"
PL_ANUAL_LINES = [
    "Ingresos", "Costo de Venta", "Margen Bruto", "Gastos de Administración y Venta",
    "Resultado Operacional (EBIT)", "Resultado No Operacional",
    "Utilidad Antes de Impuestos", "Utilidad Después de Impuestos", "Depreciación", "EBITDA",
]


def pl_anual():
    """EERR anual por año (MM CLP), desde la hoja P&L (sección 'Resumen EERR y EBITDA').
    Devuelve un DataFrame índice=línea, columnas=año.
    """
    df = D.pyl()
    if df is None or df.empty:
        return pd.DataFrame()
    res = df[df["seccion"].astype(str).str.startswith("Resumen EERR")]
    res = res[res["linea"].isin(PL_ANUAL_LINES)]
    piv = res.pivot_table(index="linea", columns="year", values="valor", aggfunc="sum") / 1000
    return piv.reindex([ln for ln in PL_ANUAL_LINES if ln in piv.index])


def ratio_anual(prefix: str) -> dict:
    """Valor del ratio al cierre (diciembre) de cada año disponible en EEFF."""
    df = D.eeff_ratios()
    if df is None or df.empty:
        return {}
    dic = df[df["month"] == 12]
    out = {}
    for y in sorted(dic["year"].unique()):
        out[int(y)] = _ratio_lookup(dic[dic["year"] == y], prefix)
    return out


# ============================================================
# BALANCE (EEFF)
# ============================================================
BAL_MAP = {
    "caja": "Caja y equivalentes",
    "existencias": "Existencias",
    "cxc": "Cuentas por Cobrar Comerciales",
    "otros_ac": "Otros Activos Corrientes de Capital",
    "total_ac": "Total Activos Corrientes",
    "ppe": "PP&E",
    "total_af": "Total Activos Fijos",
    "total_activos": "Total Activos",
    "cxp": "Cuentas por Pagar Comerciales",
    "total_pc": "Total Pasivos Corrientes",
    "deuda_rev": "Deuda Revolving",
    "deuda_fin": "Deuda financiera",
    "total_pasivos": "Total Pasivos",
    "cap": "Capital emitido",
    "gan_acum": "Ganancias acumuladas",
    "result_per": "Resultados del periodo",
    "patrimonio": "Total Patrimonio",
}


def balance_periodos() -> list[tuple[int, int]]:
    return _periodos(D.eeff())


def balance_mes(year: int, month: int) -> dict:
    df = D.eeff()
    sub = df[(df["year"] == year) & (df["month"] == month)]
    out = {}
    for k, label in BAL_MAP.items():
        v = _first(sub, "valor", label, exact=(k not in ("cxc", "otros_ac", "cxp")))
        out[k] = v / 1000 if v is not None else None
    return out


def balance_tabla(year: int, month: int) -> pd.DataFrame:
    """Balance en orden de hoja, en MM, con % s/total activos."""
    df = D.eeff()
    sub = df[(df["year"] == year) & (df["month"] == month)].copy()
    if sub.empty:
        return sub
    ta = _first(sub, "valor", "Total Activos", exact=True) or 1
    sub = sub[~sub["linea"].str.startswith("Check")]
    sub["MM"] = sub["valor"] / 1000
    sub["pct"] = sub["valor"] / ta
    return sub[["seccion", "linea", "MM", "pct"]].reset_index(drop=True)


# ============================================================
# RATIOS (EEFF 138-157)
# ============================================================
# (prefijo, nombre display, formato, categoría, mejor_si_sube, benchmark de mercado)
RATIO_CATALOGO = [
    ("Ratio Liquidez - Razón Corriente", "Razón corriente", "x", "Liquidez", True, "1,5 – 2,0×"),
    ("Ratio Liquidez - Quick Ratio", "Prueba ácida (quick ratio)", "x", "Liquidez", True, "> 1,0×"),
    ("Ratio Liquidez - Cash Ratio", "Cash ratio", "x", "Liquidez", True, "> 0,2×"),
    ("Rotación de Inventarios", "Rotación de inventarios", "x", "Gestión", True, "> 3×"),
    ("RA", "Rotación de activos", "x", "Gestión", True, "> 0,3×"),
    ("CxC", "Días de cobro (DSO)", "d", "Gestión", False, "< 45 días"),
    ("CxP", "Días de pago (DPO)", "d", "Gestión", True, "30 – 60 días"),
    ("Relación Deuda Patrimonio (Deuda", "Deuda total / Patrimonio", "x", "Endeudamiento y cobertura", False, "< 2,0×"),
    ("Relación Deuda Patrimonio - CP", "Deuda financiera / Patrimonio", "x", "Endeudamiento y cobertura", False, "< 2,0×"),
    ("Razón Endeudamiento", "Razón de endeudamiento", "x", "Endeudamiento y cobertura", False, "< 0,6"),
    ("Razón de Deuda Financiera Ebitda Neta", "Deuda financiera neta / EBITDA", "x", "Endeudamiento y cobertura", False, "< 4,0×"),
    ("Razón de Deuda Financiera Ebitda", "Deuda financiera / EBITDA", "x", "Endeudamiento y cobertura", False, "< 4,0×"),
    ("Cobertura Gastos Financieros", "Cobertura de gastos financieros", "x", "Endeudamiento y cobertura", True, "> 2,0×"),
    ("DSCR", "DSCR (servicio de deuda)", "x", "Endeudamiento y cobertura", True, "> 1,2"),
    ("ROE", "ROE", "p", "Rentabilidad", True, "> 15%"),
    ("ROA", "ROA", "p", "Rentabilidad", True, "> 8%"),
    ("EBIT (%", "Margen EBIT", "p", "Rentabilidad", True, "> 5%"),
    ("Utilidad Neta (%", "Margen neto", "p", "Rentabilidad", True, "> 5%"),
    ("GMROI-WK", "GMROI (working capital)", "p", "Rentabilidad", True, "> 1,0×"),
    ("GMROI", "GMROI", "p", "Rentabilidad", True, "> 1,0×"),
]
# umbrales numéricos para semáforo (bueno, malo, invertido) por prefijo
RATIO_UMBRAL = {
    "Ratio Liquidez - Razón Corriente": (1.5, 1.0, False),
    "Ratio Liquidez - Quick Ratio": (1.0, 0.7, False),
    "Ratio Liquidez - Cash Ratio": (0.2, 0.1, False),
    "Rotación de Inventarios": (3.0, 2.0, False),
    "RA": (0.3, 0.2, False),
    "CxC": (45, 60, True),
    "CxP": (30, 20, False),
    "Relación Deuda Patrimonio (Deuda": (2.0, 3.0, True),
    "Relación Deuda Patrimonio - CP": (2.0, 3.0, True),
    "Razón Endeudamiento": (0.6, 0.75, True),
    "Razón de Deuda Financiera Ebitda Neta": (4.0, 6.0, True),
    "Razón de Deuda Financiera Ebitda": (4.0, 6.0, True),
    "Cobertura Gastos Financieros": (2.0, 1.0, False),
    "DSCR": (1.2, 1.0, False),
    "ROE": (0.15, 0.05, False),
    "ROA": (0.08, 0.03, False),
    "EBIT (%": (0.05, 0.02, False),
    "Utilidad Neta (%": (0.05, 0.02, False),
    "GMROI-WK": (1.0, 0.8, False),
    "GMROI": (1.0, 0.8, False),
}


def semaforo_ratio(prefix, valor):
    """🟢/🟡/🔴 según el benchmark de mercado del indicador."""
    if valor is None or prefix not in RATIO_UMBRAL:
        return "⚪"
    bueno, malo, inv = RATIO_UMBRAL[prefix]
    v = -valor if inv else valor
    b = -bueno if inv else bueno
    m = -malo if inv else malo
    return "🟢" if v >= b else ("🟡" if v >= m else "🔴")


def ratios_periodos() -> list[tuple[int, int]]:
    return _periodos(D.eeff_ratios())


def _ratio_lookup(sub, prefix):
    ex = sub[sub["ratio"] == prefix]["valor"]
    if len(ex):
        return float(ex.iloc[0])
    st = sub[sub["ratio"].astype(str).str.startswith(prefix)]["valor"]
    return float(st.iloc[0]) if len(st) else None


def ratio_val(year: int, month: int, prefix: str):
    df = D.eeff_ratios()
    sub = df[(df["year"] == year) & (df["month"] == month)]
    return _ratio_lookup(sub, prefix)


def ratios_tabla(year: int, month: int, y_prev: int, m_prev: int) -> pd.DataFrame:
    """Catálogo de ratios con valor actual, comparativo (YoY) y semáforo de mejora."""
    df = D.eeff_ratios()
    cur = df[(df["year"] == year) & (df["month"] == month)]
    prev = df[(df["year"] == y_prev) & (df["month"] == m_prev)]
    rows = []
    for prefix, nombre, fmt, cat, up, bench in RATIO_CATALOGO:
        a = _ratio_lookup(cur, prefix)
        b = _ratio_lookup(prev, prefix)
        mejora = None
        if a is not None and b is not None and a != b:
            mejora = ((a > b) == up)
        rows.append({"categoria": cat, "indicador": nombre, "fmt": fmt,
                     "actual": a, "previo": b, "mejora": mejora,
                     "benchmark": bench, "semaforo": semaforo_ratio(prefix, a)})
    return pd.DataFrame(rows)


# ============================================================
# DEUDA
# ============================================================
def deuda_periodos() -> list[tuple[int, int]]:
    return _periodos(D.deuda())


def deuda_composicion(year: int, month: int) -> dict:
    df = D.deuda()
    sub = df[(df["year"] == year) & (df["month"] == month) & (df["linea"] == "Saldo final")]
    if sub.empty or "bloque" not in sub.columns:
        return {}
    comp = sub.groupby("bloque")["valor"].first()
    return {k: v / 1000 for k, v in comp.items()}


def deuda_bancos_comex(year: int, month: int) -> dict:
    df = D.deuda()
    if "bloque" not in df.columns:
        return {}
    sub = df[(df["year"] == year) & (df["month"] == month) & (df["bloque"] == "COMEX")]
    bancos = ["Santander", "Itaú", "Scotiabank", "BCI", "Security",
              "Internacional", "Consorcio", "Banco de Chile"]
    out = {}
    for b in bancos:
        s = sub[sub["linea"] == b]["valor"]
        if len(s) and abs(s.iloc[0]) > 1e-6:
            out[b] = float(s.iloc[0]) / 1000
    return out


def deuda_intereses(year: int, month: int) -> float | None:
    """Gasto en intereses del mes (suma de todos los bloques), en MM."""
    df = D.deuda()
    sub = df[(df["year"] == year) & (df["month"] == month) &
             (df["linea"].astype(str).str.startswith("Gasto en interes"))]
    return float(sub["valor"].sum()) / 1000 if len(sub) else None


def deuda_detalle(year: int, month: int) -> list[dict]:
    """Por bloque de deuda: saldo + gasto en intereses del mes (MM)."""
    df = D.deuda()
    if df is None or df.empty or "bloque" not in df.columns:
        return []
    sub = df[(df["year"] == year) & (df["month"] == month)]
    out = []
    for bloque in ["COMEX", "Comercial", "Socios"]:
        bs = sub[sub["bloque"] == bloque]
        saldo = bs[bs["linea"] == "Saldo final"]["valor"]
        inter = bs[bs["linea"].astype(str).str.startswith("Gasto en interes")]["valor"]
        out.append({
            "bloque": bloque,
            "saldo": float(saldo.iloc[0]) / 1000 if len(saldo) else None,
            "intereses": float(inter.sum()) / 1000 if len(inter) else None,
        })
    return out


def deuda_evolucion() -> pd.DataFrame:
    """Serie mensual del saldo total de deuda financiera (MM)."""
    df = D.deuda()
    if df is None or df.empty or "bloque" not in df.columns:
        return pd.DataFrame()
    tot = df[(df["bloque"] == "Total") & (df["linea"] == "Saldo final")].copy()
    tot["MM"] = tot["valor"] / 1000
    return tot.sort_values("fecha")[["fecha", "MM"]]


def prestamos_tabla() -> pd.DataFrame:
    df = D.prestamos()
    return df.copy() if df is not None else pd.DataFrame()


def cuotas_proyeccion(year: int, month: int, horizonte: int = 18) -> list[tuple[int, int, float]]:
    """Proyección de cuotas comprometidas por mes: [(year, month, total_MM)].
    Cada crédito aporta su cuota mensual mientras le queden cuotas pendientes."""
    pres = prestamos_tabla()
    if pres.empty:
        return []
    pres = pres.dropna(subset=["cuotas_pend", "cuota_mensual"])
    out = []
    for i in range(horizonte):
        m0 = month + 1 + i
        y = year + (m0 - 1) // 12
        m = (m0 - 1) % 12 + 1
        tot = float(pres.loc[pres["cuotas_pend"] > i, "cuota_mensual"].sum()) / 1e6
        out.append((y, m, tot))
    return out


# ============================================================
# KT  (capital de trabajo + existencias)
# ============================================================
def kt_periodos() -> list[tuple[int, int]]:
    return _periodos(D.kt())


def kt_serie(linea: str = "Meses de existencias móvil") -> pd.DataFrame:
    """Serie mensual de una línea de la hoja KT (fecha, valor)."""
    df = D.kt()
    if df is None or df.empty:
        return pd.DataFrame()
    s = df[df["linea"] == linea].sort_values("fecha")
    return s[["fecha", "valor"]].copy()


def kt_mes(year: int, month: int) -> dict:
    df = D.kt()
    sub = df[(df["year"] == year) & (df["month"] == month)]

    def money(linea, exact=True):
        v = _first(sub, "valor", linea, exact=exact)
        return v / 1000 if v is not None else None

    def ratio(linea):
        v = _first(sub, "valor", linea, exact=True)
        return v

    return {
        "existencias": money("Existencias"),
        "iw": money("Existencias IW"),
        "it": money("Existencias IT"),
        "mp": money("Materia Primas"),
        "cxc": money("Cuentas por Cobrar Comerciales", exact=False),
        "cxp": money("Cuentas por Pagar Comerciales", exact=False),
        "otros_ac": money("Otros Activos Corrientes de Capital", exact=False),
        "total_ac": money("Total Activos Corrientes", exact=False),
        "ktneto": money("Capital de trabajo neto"),
        "meses_exist": ratio("Meses de existencias móvil"),
        "meses_iw": ratio("Meses de Existencias IW"),
        "meses_it": ratio("Meses de Existencias IT"),
        "meses_mp": ratio("Meses de Materias Primas"),
        "meses_cxc": ratio("Meses de CxC"),
        "meses_cxp": ratio("Meses de CxP"),
        "uso": ratio("% Uso"),
        "pos_tomadas": ratio("Posiciones Tomadas"),
        "cap_total": ratio("Capacidad Total"),
    }


# ============================================================
# PP&E (activo fijo)
# ============================================================
def ppe_periodos() -> list[tuple[int, int]]:
    return _periodos(D.ppe())


def ppe_mes(year: int, month: int) -> dict:
    df = D.ppe()
    sub = df[(df["year"] == year) & (df["month"] == month)]

    def g(linea, exact=True):
        v = _first(sub, "valor", linea, exact=exact)
        return v / 1000 if v is not None else None

    return {
        "bruto": g("Saldo final Activo Fijo Bruto"),
        "deprec_acum": g("Depreciación acumulada final"),
        "neto": g("Activo Fijo Neto"),
        "capex": g("(+) Nuevas inversiones", exact=False),
        "gasto_deprec": g("(-) Gasto por depreciación", exact=False),
        "tabla": sub[["seccion", "linea", "valor"]].assign(MM=lambda d: d["valor"] / 1000),
    }


# ============================================================
# Otros activos y pasivos
# ============================================================
def otros_periodos() -> list[tuple[int, int]]:
    return _periodos(D.otros_activos_pasivos())


def otros_mes(year: int, month: int) -> dict:
    df = D.otros_activos_pasivos()
    sub = df[(df["year"] == year) & (df["month"] == month)]

    def g(linea):
        v = _first(sub, "valor", linea, exact=True)
        return v / 1000 if v is not None else None

    return {
        "total_activos": g("Total Otros Activos"),
        "total_pasivos": g("Total Otros Pasivos"),
        "cambio_neto": g("Cambio en Otros Activos y Pasivos"),
        "tabla": sub[["seccion", "linea", "valor"]].assign(MM=lambda d: d["valor"] / 1000),
    }


# ============================================================
# FORMATTERS
# ============================================================
def fmt_mm(v, dec: int = 0) -> str:
    """MM CLP → '$X M' (miles de millones se ven grandes, es lo esperado)."""
    if v is None or pd.isna(v):
        return "—"
    s = f"{abs(v):,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return ("−$" if v < 0 else "$") + s + " M"


def fmt_mm_md(v, dec: int = 0) -> str:
    """fmt_mm con '$' escapado para st.markdown/info/warning (evita LaTeX)."""
    return fmt_mm(v, dec).replace("$", "\\$")


def fmt_ratio(v, fmt: str = "x") -> str:
    if v is None or pd.isna(v):
        return "—"
    if fmt == "p":
        return f"{v * 100:.1f}%".replace(".", ",")
    if fmt == "d":
        return f"{v:.0f} d"
    return (f"{v:.1f}" if abs(v) >= 1 else f"{v:.2f}").replace(".", ",") + "×"


def fmt_pct_venta(v, venta) -> str:
    if v is None or venta in (None, 0) or pd.isna(v):
        return "—"
    return f"{v / venta * 100:.1f}%".replace(".", ",")


def fmt_var(pct) -> str:
    if pct is None or pd.isna(pct):
        return "—"
    return f"{pct * 100:+.1f}%".replace(".", ",")


def yoy(a, b):
    if a is None or b in (None, 0) or pd.isna(a) or pd.isna(b):
        return None
    return a / b - 1
