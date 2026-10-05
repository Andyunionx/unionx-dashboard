# -*- coding: utf-8 -*-
"""
Proyección de cierre del mes en curso ("¿cómo vamos y cómo cerramos?") — motor del
dashboard de cierre (dashboard_cierre.py). Reglas definidas por Andrés (23/24-sep-2026).

Fuentes
  - Venta y costo del mes: ventas_mes_actual.parquet en su versión de PRODUCCIÓN (origin/main).
  - Documentos excluidos caso a caso y márgenes corregidos: data/finanzas/cierre_mes_ajustes.json.
  - Comparación: venta, margen directo y de contribución contra el Fcst EERR del mes; GAV contra
    la hoja FCST GASTO 2026 (Tabla 2). El PPTO VENTAS 2026 / Metas 2026 quedan de referencia.
  - Proyección del GAV y depreciación: resultado vigente del Fcst EERR.

Venta
  - Marketplace, Fidelización, Páginas Web y canal UnionX B2B: curva del año anterior alineada
    por día de semana (−364 días: Cyber y Black Friday calzan; backtest ene-sep 2026: error medio
    12% al día 4 → 3% al día 10). Las operaciones puntuales ≥ $5M no se extrapolan: van tal cual.
  - Distribución y Corporativo: se asume que cumplen el FCST (o lo real, si ya lo supera).

Margen
  - Margen directo (venta − costo): real a la fecha + resto del mes al % del flujo normal.
  - Margen de contribución base por línea: resultado del mes anterior del Drive "Seguimiento
    contribuciones 2026" (Marketplace, Fidelización, Web; en el cierre, el del propio mes), corregido
    por estacionalidad con los pp de margen directo del año anterior (mes vs mes base: el Cyber
    baja el margen); % del FCST VENTAS para Distribución y Corporativo. El RAW no trae la contribución completa a tiempo: solo se muestra como señal.
  - Operaciones puntuales ≥ $5M por documento: se aíslan con su margen propio (RAW), corregible.

  - Insumos (etiquetas y envases): 0,3% de la venta, se descuentan del margen de contribución de
    cada línea (Andrés 5-oct; el Drive de seguimiento no los trae). Medios de pago van dentro de la
    comisión de venta y los fletes dentro de la logística.

EBITDA = margen de contribución − GAV + depreciación (igual que la planilla).
Uso: python cierre_mes.py   ·   from cierre_mes import proyectar_cierre
"""
from __future__ import annotations

import calendar
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
RECURRENTES = {"marketplace", "fidelización", "fidelizacion", "páginas propias", "paginas propias"}
CANALES_RECURRENTES_EXTRA = {"unionx b2b"}
LINEA = {"marketplace": "Marketplace", "fidelización": "Fidelización", "fidelizacion": "Fidelización",
         "páginas propias": "Páginas Web", "paginas propias": "Páginas Web",
         "distribución": "Distribución", "distribucion": "Distribución", "corporativo": "Corporativo"}
LINEAS_META = ("Marketplace", "Distribución", "Fidelización", "Páginas Web", "Corporativo")
BANDA_MC = 0.03
INSUMOS_PCT = 0.003   # insumos (etiquetas y envases) sobre la venta, regla de Andrés 5-oct-2026
PARQUET_MES = "data/historico/ventas_mes_actual.parquet"


def _tn(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.lower().str.strip()


# ------------------------------------------------------------------ fuentes
def _parquet_produccion() -> tuple[Path, str]:
    """Versión de producción del parquet del mes (origin/main). En GitHub Actions el
    checkout ya es producción. Fallback: copia local."""
    local = ROOT / PARQUET_MES
    if os.environ.get("GITHUB_ACTIONS"):
        return local, "producción"
    try:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, timeout=90, check=True,
                       capture_output=True)
        blob = subprocess.run(["git", "show", f"origin/main:{PARQUET_MES}"], cwd=ROOT, timeout=90,
                              check=True, capture_output=True).stdout
        dest = Path(tempfile.gettempdir()) / "unionx_ventas_mes_actual_origin.parquet"
        dest.write_bytes(blob)
        return dest, "producción"
    except Exception:
        return local, "copia local (sin acceso a producción)"


def _excluidos() -> list[dict]:
    path = ROOT / "data/finanzas/cierre_mes_ajustes.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("excluir_documentos", [])


def _ventas_linea(nombre: str, anio: int, mes: int) -> dict:
    """{linea: {'venta': MM, 'contribucion': MM}} desde fcst_ventas_2026 / ppto_ventas_2026."""
    path = ROOT / f"data/finanzas/{nombre}.parquet"
    if not path.exists():
        return {}
    d = pd.read_parquet(path)
    d = d[(d.year == anio) & (d.month == mes)]
    out = {}
    for _, r in d.iterrows():
        out.setdefault(r.linea_negocio, {"venta": 0.0, "contribucion": 0.0})[r.kpi] = r.valor / 1e6
    return out


def _metas_2026(anio: int, mes: int) -> dict:
    """Meta del mes: venta y contribución de PPTO VENTAS 2026 (fallback Metas 2026), GAV de
    Metas 2026. EBITDA = contribución − GAV."""
    m = pd.read_parquet(ROOT / "data/finanzas/metas_2026.parquet")
    s = m[(m["year"] == anio) & (m["month"] == mes) & (m["tipo"] == "Meta")]

    def k(nombre):
        return float(s[s["kpi"].astype(str).str.startswith(nombre[:6])]["valor"].sum()) / 1e6
    pv = _ventas_linea("ppto_ventas_2026", anio, mes)
    venta = sum(v["venta"] for v in pv.values()) if pv else k("Venta")
    contrib = sum(v["contribucion"] for v in pv.values()) if pv else k("Contribución")
    gav = k("GAV")
    return {"Venta": venta, "Contribución": contrib, "GAV": gav, "EBITDA": contrib - gav}


def _metas_canal(anio: int, mes: int, ppto_linea: dict) -> dict:
    """Meta por canal: plan comercial V06 escalado, dentro de cada línea, al PPTO de la línea."""
    path = ROOT / "data/planificacion/metas_canal_mensuales_2026.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = {}
    for r in data.get("metas", []):
        if not str(r.get("canal") or "").strip():
            continue          # metas por línea sin canal (oct-dic 2026, FCST VENTAS): no son de canal
        if int(r.get("ano", 0)) == anio and int(r.get("mes", 0)) == mes:
            lin = LINEA.get(str(r["negocio"]).strip().lower(), str(r["negocio"]).strip())
            c = str(r["canal"]).strip().lower()
            c = {"latam": "latam pass"}.get(c, c)
            raw.setdefault(lin, {})
            raw[lin][c] = raw[lin].get(c, 0) + float(r.get("meta_venta", 0)) / 1e6
    out = {}
    for lin, canales in raw.items():
        tot = sum(canales.values())
        objetivo = ppto_linea.get(lin, {}).get("venta", tot)
        f = objetivo / tot if tot else 1
        for c, v in canales.items():
            out[c] = out.get(c, 0) + v * f
    return out


def _calibracion(anio: int, mes: int, hist: pd.DataFrame) -> dict:
    """Último mes cerrado con comisión/logística completas en el RAW (ago-2026+): tasa
    (comisión+logística)/venta por tipo de negocio y ajuste k = MC% contable − MC% modelo."""
    f = pd.read_parquet(ROOT / "data/finanzas/fcst_eerr.parquet")
    y, m = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    for _ in range(6):
        if (y, m) < (2026, 8):
            break
        s = f[(f["year"] == y) & (f["month"] == m)]
        venta_c = s[s["linea"] == "Ingreso de Explotación"]["valor_fcst"].sum()
        mc_c = s[s["linea"] == "Margen de Contribución"]["valor_fcst"].sum()
        h = hist[(hist.fecha_venta.dt.year == y) & (hist.fecha_venta.dt.month == m)].copy()
        if venta_c and len(h):
            h["tn"] = _tn(h["tipo_negocio"])
            g = h.groupby("tn")[["venta_neta", "costo_total", "comision", "logistica"]].sum()
            cl = ((g.comision + g.logistica) / g.venta_neta).fillna(0).to_dict()
            mod = (g.venta_neta - g.costo_total - g.comision - g.logistica).sum() / g.venta_neta.sum()
            return {"mes": f"{MESES[m - 1]}-{str(y)[2:]}", "cl": cl, "k": mc_c / venta_c - mod}
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return {"mes": "—", "cl": {}, "k": 0.0}


UMBRAL_PUNTUAL_MM = 5.0


def _fcst_eerr_mes(anio: int, mes: int) -> dict:
    """Forecast vigente del mes desde la hoja Fcst EERR (real en meses cerrados, forecast en los
    abiertos): venta, margen de contribución, GAV, EBITDA y D&A (= EBITDA − resultado operacional)."""
    f = pd.read_parquet(ROOT / "data/finanzas/fcst_eerr.parquet")
    s = f[(f.year == anio) & (f.month == mes)].groupby("linea").valor_fcst.sum() / 1e6
    g = lambda l: float(s.get(l, 0.0))
    ebitda = g("EBITDA")
    return {"Venta": g("Ingreso de Explotación"), "Contribución": g("Margen de Contribución"),
            "MD": g("Margen de Explotación"),
            "GAV": abs(g("TOTAL GAV")), "EBITDA": ebitda, "DA": ebitda - g("RESULTADO OPERACIONAL")}


SEGUIMIENTO_ID = "1d7iN4M-AoNZvBEXxvGWYK5pJoXAI6VxzJIdjh12QNjM"   # Drive "Seguimiento contribuciones 2026"
MESES_LARGO = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
               "Septiembre", "Octubre", "Noviembre", "Diciembre"]
TOTALES_SEG = {"Total MKP": "Marketplace", "Total FD": "Fidelización", "Total WEB": "Páginas Web"}


def _num_cl(s: str):
    s = str(s).replace("$", "").replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _contrib_seguimiento(anio: int, mes: int, incluir_mes: bool = False) -> dict:
    """Margen de contribución % por línea del último mes CERRADO, desde el bloque 'Resultado <Mes>'
    de la pestaña 'Resumen 2026' del Drive de seguimiento de contribución. Con `incluir_mes` (cierre
    del mes) usa el resultado del propio mes si ya está. Cachea en
    data/finanzas/contribucion_seguimiento.json (fallback si no hay acceso al Drive)."""
    cache = ROOT / "data/finanzas/contribucion_seguimiento.json"
    datos = {}
    try:
        sys.path.insert(0, str(ROOT))
        from drive_user_helpers import _credentials
        import gspread
        v = gspread.authorize(_credentials()).open_by_key(SEGUIMIENTO_ID).worksheet("Resumen 2026").get_all_values()
        h1, h2 = v[0], v[1]
        for i, c in enumerate(h1):
            c = c.strip()
            if not c.startswith("Resultado "):
                continue
            nombre = c.replace("Resultado ", "")
            if nombre not in MESES_LARGO:
                continue
            cols = {h2[j].strip(): j for j in range(i, min(i + 8, len(h2)))}
            ci, vi = cols.get("Contri $"), cols.get("Venta")
            if ci is None or vi is None:
                continue
            m_ = MESES_LARGO.index(nombre) + 1
            for r in v[2:]:
                lab = (r[3] or r[1]).strip()
                if lab in TOTALES_SEG:
                    cc, vv = _num_cl(r[ci]), _num_cl(r[vi])
                    if cc is not None and vv:
                        datos.setdefault(str(m_), {})[TOTALES_SEG[lab]] = {"contri": cc / 1e6, "venta": vv / 1e6}
        cache.write_text(json.dumps({"anio": 2026, "meses": datos}, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        if cache.exists():
            datos = json.loads(cache.read_text(encoding="utf-8")).get("meses", {})
    # último mes cerrado anterior al mes en curso (o el propio mes, en el cierre)
    for m_ in range(mes if incluir_mes else mes - 1, 0, -1):
        d = datos.get(str(m_))
        if d:
            return {"mes": f"{MESES[m_ - 1]}-{str(anio)[2:]}", "num": m_,
                    "pct": {k: x["contri"] / x["venta"] for k, x in d.items() if x["venta"]}}
    return {"mes": "—", "num": None, "pct": {}}


def _estacionalidad_margen(hist: pd.DataFrame, anio: int, mes: int, mes_base: int | None) -> dict:
    """pp de margen directo por línea entre el mes y el mes base, ambos del año anterior (RAW).
    En los meses de Cyber el margen cae (oct-25 vs sep-25: Marketplace −7,7 pp, Web −8,1 pp) y al mes
    siguiente se recupera; el resultado del mes base se corrige con ese delta (Andrés 5-oct)."""
    if not mes_base or mes_base == mes:
        return {}
    h = hist[hist.fecha_venta.dt.year == anio - 1].copy()
    h["lin"] = _tn(h["tipo_negocio"]).map(LINEA)

    def delta(x):
        a, b = x[x.fecha_venta.dt.month == mes], x[x.fecha_venta.dt.month == mes_base]
        if a.venta_neta.sum() >= 20e6 and b.venta_neta.sum() >= 20e6:
            return (b.costo_total.sum() / b.venta_neta.sum()) - (a.costo_total.sum() / a.venta_neta.sum())
        return None
    lineas = ("Marketplace", "Fidelización", "Páginas Web")
    total = delta(h[h["lin"].isin(lineas)])
    out = {}
    for lin in lineas:
        d = delta(h[h["lin"] == lin])
        d = total if d is None else d          # línea chica el año anterior: delta del total recurrente
        if d is not None:
            out[lin] = d
    return out


def _fcst_gasto_mes(anio: int, mes: int) -> dict:
    """Forecast del GAV del mes desde la hoja FCST GASTO 2026 (Tabla 2): GAV y depreciación."""
    path = ROOT / "data/finanzas/fcst_gasto_2026.parquet"
    if not path.exists():
        return {}
    g = pd.read_parquet(path)
    g = g[(g.year == anio) & (g.month == mes)].set_index("centro_costo").valor / 1e6
    return {"GAV": float(g.get("GAV", 0.0)), "DA": float(g.get("DEPRECIACIÓN", 0.0))}


def _ajustes() -> dict:
    path = ROOT / "data/finanzas/cierre_mes_ajustes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ------------------------------------------------------------------ proyección
UMBRAL_CONFIABLE = 0.25   # bajo este % del mes (curva LY) la proyección se mezcla con el FCST


def _hoy_chile() -> date:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("America/Santiago")).date()
    except Exception:
        return date.today()


def es_primer_dia_habil(d: date) -> bool:
    """Primer día lunes a viernes del mes (el 1, o el lunes 2/3 si el 1 cae en fin de semana)."""
    return d.weekday() < 5 and (d.day == 1 or (d.weekday() == 0 and d.day <= 3))


def proyectar_cierre(hoy: date | None = None) -> dict:
    """`hoy` = fecha de la corrida (por defecto, hoy en Chile). Se proyecta con el último día
    COMPLETO (hoy − 1): el día en curso está a medio capturar (Andrés 1-oct-2026). El día 1 del mes
    eso deja el mes anterior completo → el dashboard sale como CIERRE real de ese mes."""
    cols = ["fecha_venta", "canal", "tipo_negocio", "documento", "venta_neta", "costo_total",
            "comision", "logistica"]
    src, fuente = _parquet_produccion()
    cur = pd.read_parquet(src, columns=cols)
    hist = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=cols)
    for df in (cur, hist):
        df["fecha_venta"] = pd.to_datetime(df["fecha_venta"])

    hoy = hoy or _hoy_chile()
    corte = pd.Timestamp(hoy) - pd.Timedelta(days=1)
    if es_primer_dia_habil(hoy):
        # Andrés 1-oct: el primer día hábil del mes va el CIERRE del mes anterior (aunque el 1 caiga en fin de semana)
        corte = pd.Timestamp(hoy.replace(day=1)) - pd.Timedelta(days=1)
    ultimo = min(cur.fecha_venta.dt.normalize().max(), corte)
    anio, mes, dia = ultimo.year, ultimo.month, ultimo.day
    if not ((cur.fecha_venta.dt.year == anio) & (cur.fecha_venta.dt.month == mes)).any():
        # el parquet del mes ya rotó: el mes a cerrar se toma del histórico
        cur = pd.read_parquet(ROOT / "data/historico/ventas_historico.parquet", columns=cols)
        cur["fecha_venta"] = pd.to_datetime(cur["fecha_venta"])
        fuente += " · mes cerrado desde el histórico"

    excl = _excluidos()
    docs_excl = {e["documento"] for e in excl}
    mask_ex = cur["documento"].isin(docs_excl)
    excluido_mm = float(cur.loc[mask_ex, "venta_neta"].sum()) / 1e6
    cur = cur[~mask_ex]

    dias_mes = calendar.monthrange(anio, mes)[1]
    cerrado = dia == dias_mes
    cur = cur[(cur.fecha_venta.dt.year == anio) & (cur.fecha_venta.dt.month == mes)
              & (cur.fecha_venta.dt.normalize() <= ultimo)].copy()
    cur["tn"] = _tn(cur["tipo_negocio"])
    cur["linea"] = cur["tn"].map(LINEA).fillna("Otros")
    cur["ck"] = cur["canal"].fillna("").str.strip().str.lower()
    cur["rec"] = cur["tn"].isin(RECURRENTES) | cur["ck"].isin(CANALES_RECURRENTES_EXTRA)

    # curva: % de la venta recurrente del año anterior hecho al corte, ALINEADA POR DÍA DE SEMANA
    # (−364 días): el Cyber (lunes de la 1ª semana de jun/oct) y el Black Friday caen en el mismo
    # día del evento que el año anterior, y los fines de semana calzan (Andrés 5-oct: el cierre de
    # oct no leía la estacionalidad). Las operaciones puntuales del año anterior no forman la curva.
    d364 = pd.Timedelta(days=364)
    ini_ly = pd.Timestamp(anio, mes, 1) - d364
    fin_ly = pd.Timestamp(anio, mes, dias_mes) - d364
    fly = hist.fecha_venta.dt.normalize()
    ly = hist[(fly >= ini_ly) & (fly <= fin_ly)].copy()
    ly = ly[_tn(ly["tipo_negocio"]).isin(RECURRENTES)]
    ly["ym"] = ly.fecha_venta.dt.to_period("M")
    dly = ly.groupby(["ym", "documento"]).venta_neta.transform("sum")
    ly = ly[~((dly.abs() >= UMBRAL_PUNTUAL_MM * 1e6) & ly["documento"].fillna("").str.strip().ne(""))]
    ly_tot = ly.venta_neta.sum()
    share = (ly[ly.fecha_venta.dt.normalize() <= ultimo - d364].venta_neta.sum() / ly_tot) if ly_tot else dia / dias_mes
    share = 1.0 if cerrado else min(max(share, 0.05), 1.0)
    # inicio de mes: pocos días de venta → la curva sola es ruido; se pondera con el FCST
    peso_curva = 1.0 if cerrado else min(1.0, share / UMBRAL_CONFIABLE)
    confiabilidad = "cerrado" if cerrado else ("baja" if peso_curva < 1 else "normal")

    ppto = _ventas_linea("ppto_ventas_2026", anio, mes)
    fcst = _ventas_linea("fcst_ventas_2026", anio, mes)
    cal = _calibracion(anio, mes, hist)
    fe = _fcst_eerr_mes(anio, mes)          # resultado/proyección vigente (hoja Fcst EERR)
    fg = _fcst_gasto_mes(anio, mes)         # forecast del gasto (hoja FCST GASTO 2026)
    ppto_mes = _metas_2026(anio, mes)       # referencia secundaria: presupuesto
    seg = _contrib_seguimiento(anio, mes, incluir_mes=cerrado)   # margen de contribución % por línea (mes anterior, o el propio en el cierre)
    est = _estacionalidad_margen(hist, anio, mes, seg.get("num"))   # pp por estacionalidad (Cyber, Black Friday)
    fe_prev = _fcst_eerr_mes(*((anio, mes - 1) if mes > 1 else (anio - 1, 12)))
    # comparación: venta y margen del forecast (Fcst EERR); GAV del FCST GASTO
    gav_fcst = fg.get("GAV") or fe["GAV"]
    da_fcst = fg.get("DA") if fg else fe["DA"]
    meta = {"Venta": fe["Venta"], "Contribución": fe["Contribución"], "GAV": gav_fcst,
            "EBITDA": fe["Contribución"] - gav_fcst + da_fcst, "MD": fe["MD"]}
    factor_cont = 1.0

    # operaciones puntuales grandes: se aíslan con su margen propio (override caso a caso)
    aj = _ajustes()
    overrides = {o["documento"]: o for o in aj.get("margen_override", [])}
    docs = (cur[cur["documento"].fillna("").str.strip() != ""]
            .groupby(["documento", "canal", "linea", "tn"])
            .agg(v=("venta_neta", "sum"), c=("costo_total", "sum")).reset_index())
    docs["v"] /= 1e6
    docs["c"] /= 1e6
    grandes = docs[docs["v"].abs() >= UMBRAL_PUNTUAL_MM]
    docs_grandes = set(grandes["documento"])

    def base_pct(lin):
        """Margen de contribución base: resultado del mes anterior (Drive de seguimiento) para
        Marketplace/Fidelización/Páginas Web; % del FCST VENTAS para Distribución y Corporativo."""
        if lin in seg["pct"]:
            return seg["pct"][lin] + est.get(lin, 0.0)
        f_lin, p_lin = fcst.get(lin, {}), ppto.get(lin, {})
        if f_lin.get("venta"):
            return f_lin["contribucion"] / f_lin["venta"]
        if p_lin.get("venta"):
            return p_lin["contribucion"] / p_lin["venta"]
        return None

    def fuente_base(lin):
        if lin not in seg["pct"]:
            return "FCST"
        e = est.get(lin)
        return f"resultado {seg['mes']}" + (f" {e * 100:+.1f} pp estacionalidad ({MESES[mes - 1].lower()} vs {MESES[seg['num'] - 1].lower()} año anterior)" if e else "")

    operaciones = []
    for _, r in grandes.iterrows():
        mgd = 1 - r.c / r.v if r.v else 0.0
        mc_raw = mgd - cal["cl"].get(r.tn, 0.0) + cal["k"]
        ov = overrides.get(r.documento)
        mc_op = float(ov["margen"]) if ov else mc_raw
        bp = base_pct(r.linea) or 0.0
        operaciones.append({"documento": r.documento, "canal": r.canal, "linea": r.linea, "venta": r.v,
                            "mgd": mgd, "mc_raw": mc_raw, "mc_pct": mc_op, "mc": r.v * mc_op,
                            "base_pct": bp, "impacto": r.v * (mc_op - bp), "override": bool(ov),
                            "motivo": ov.get("motivo", "") if ov else ""})

    lineas = []
    for lin in list(LINEAS_META) + ["Otros"]:
        s = cur[cur["linea"] == lin]
        acum = s.venta_neta.sum() / 1e6
        rec_acum = s.loc[s["rec"], "venta_neta"].sum() / 1e6
        no_rec = acum - rec_acum
        # las operaciones puntuales (≥ $5M por documento) no se repiten: van tal cual, sin curva
        # (Andrés 5-oct: la FAC 102855 de $25M extrapolada llevó Distribución a $412M vs FCST $46M)
        punt_rec = s.loc[s["rec"] & s["documento"].isin(docs_grandes), "venta_neta"].sum() / 1e6
        rec_norm = rec_acum - punt_rec
        f_lin = fcst.get(lin, {"venta": 0.0, "contribucion": 0.0})
        p_lin = ppto.get(lin, {"venta": 0.0, "contribucion": 0.0})
        if cerrado:
            proy, regla = acum, "real (mes cerrado)"
        elif lin in ("Distribución", "Corporativo"):
            base = no_rec + punt_rec + rec_norm / share
            proy = max(base, f_lin["venta"])
            regla = "FCST (se asume cumplido)" if f_lin["venta"] > base else "real (ya supera el FCST)"
        elif lin == "Otros":
            proy, regla = acum, "real"
        else:
            proy, regla = rec_norm / share + punt_rec + no_rec, "curva año anterior"
            if peso_curva < 1 and f_lin["venta"]:
                proy = max(peso_curva * proy + (1 - peso_curva) * f_lin["venta"], acum)
                regla = f"curva {peso_curva * 100:.0f}% + FCST {100 - peso_curva * 100:.0f}% (inicio de mes)"
        lineal = (rec_norm / dia * dias_mes + punt_rec + no_rec) if lin not in ("Distribución", "Corporativo") else proy

        ops = [o for o in operaciones if o["linea"] == lin]
        punt_v = sum(o["venta"] for o in ops)
        punt_mc = sum(o["mc"] for o in ops)
        bp = base_pct(lin)
        normal = s[~s["documento"].isin(docs_grandes)]
        # señal del RAW (solo referencia): margen del flujo normal del mes
        nv = normal.venta_neta.sum() / 1e6
        cl = (sum(cal["cl"].get(t, 0.0) * normal.loc[normal.tn == t, "venta_neta"].sum() for t in normal.tn.unique())
              / normal.venta_neta.sum()) if normal.venta_neta.sum() else 0.0
        mc_senal = (1 - normal.costo_total.sum() / 1e6 / nv) - cl + cal["k"] if nv else None
        if bp is None:
            bp = mc_senal if mc_senal is not None else 0.0
        normal_proy = max(proy - punt_v, 0.0)
        mc_proy_l = normal_proy * bp + punt_mc - INSUMOS_PCT * proy
        mc_acum_l = max(acum - punt_v, 0.0) * bp + punt_mc - INSUMOS_PCT * acum
        # margen directo (venta − costo): el costo del RAW sí es oportuno → real a la fecha;
        # el resto del mes al % directo del flujo normal (o al del FCST si no hay venta aún)
        md_acum = acum - s.costo_total.sum() / 1e6
        f_md = (f_lin.get("margen_directo", 0.0) / f_lin["venta"]) if f_lin.get("venta") else None
        md_pct_normal = (1 - normal.costo_total.sum() / 1e6 / nv) if nv else (f_md or 0.0)
        md_proy_l = md_acum + max(proy - acum, 0.0) * md_pct_normal
        if acum == 0 and proy == 0:
            continue
        lineas.append({"linea": lin, "acum": acum, "proy": proy, "lineal": lineal, "regla": regla,
                       "fuente_base": fuente_base(lin), "md_acum": md_acum, "md_proy": md_proy_l,
                       "md_fcst": f_lin.get("margen_directo", 0.0),
                       "meta_venta": f_lin["venta"], "meta_mc": f_lin["contribucion"] * factor_cont,
                       "fcst_venta": f_lin["venta"], "ppto_venta": p_lin["venta"],
                       "base_pct": bp, "mc_senal": mc_senal, "puntual_venta": punt_v, "puntual_mc": punt_mc,
                       "mc_proy": mc_proy_l, "mc_acum": mc_acum_l,
                       "mc_pct": mc_proy_l / proy if proy else 0.0})

    venta_acum = sum(l["acum"] for l in lineas)
    venta_proy = sum(l["proy"] for l in lineas)
    venta_lineal = sum(l["lineal"] for l in lineas)
    mc_proy = sum(l["mc_proy"] for l in lineas)
    mc_acum = sum(l["mc_acum"] for l in lineas)
    costo_acum = cur.costo_total.sum() / 1e6
    rec_acum_tot = cur.loc[cur["rec"], "venta_neta"].sum() / 1e6
    # proyección del gasto = resultado vigente del Fcst EERR (GAV y depreciación del mes)
    gav_proy, da_proy = fe["GAV"], fe["DA"]
    ebitda_proy = mc_proy - gav_proy + da_proy
    md_proy = sum(l["md_proy"] for l in lineas)
    md_acum = sum(l["md_acum"] for l in lineas)
    fcst_venta, fcst_mc = fe["Venta"], fe["Contribución"]

    # desviaciones por canal recurrente (meta V06 escalada al FCST de su línea)
    mcanal = _metas_canal(anio, mes, fcst)
    sin_meta_canal = not mcanal
    rec = cur[cur["rec"]]
    nombres = {c.strip().lower(): c for c in rec["canal"].dropna().unique()}
    es_punt = rec["documento"].isin(docs_grandes)
    vc = (rec[~es_punt].groupby("ck").venta_neta.sum() / 1e6 / share).add(
        rec[es_punt].groupby("ck").venta_neta.sum() / 1e6, fill_value=0).to_dict()
    if sin_meta_canal or peso_curva < 1:
        vc = {}          # sin meta por canal, o muy pocos días: no se publican desviaciones por canal
    canal_linea = dict(zip(rec["ck"], rec["linea"]))
    # Distribución y Corporativo no se comparan por canal: en el plan V06 toda la meta de
    # distribución está en "UnionX b2b" y la venta real entra por el canal del cliente.
    excl_canal = {"corporativo", "unionx b2b"} | {k for k, v in canal_linea.items() if v == "Distribución"}
    claves = (set(mcanal) | set(vc)) - excl_canal if vc else set()
    desv = [(nombres.get(c, c.title()), vc.get(c, 0.0), mcanal.get(c, 0.0), vc.get(c, 0.0) - mcanal.get(c, 0.0))
            for c in claves]
    desv = [d for d in desv if abs(d[3]) >= 1]
    desv.sort(key=lambda d: d[3])
    diario = (cur.groupby(cur.fecha_venta.dt.day).venta_neta.sum() / 1e6).reindex(range(1, dia + 1), fill_value=0)

    negocios = sorted([(l["linea"], l["proy"], l["meta_venta"], l["proy"] - l["meta_venta"])
                       for l in lineas if l["linea"] != "Otros"], key=lambda d: d[3])
    gap_ebitda = ebitda_proy - meta["EBITDA"]
    rel = gap_ebitda / meta["Venta"] if meta["Venta"] else 0
    semaforo = "verde" if rel >= 0 else ("amarillo" if rel >= -0.02 else "rojo")

    return {
        "anio": anio, "mes": mes, "etiqueta": f"{MESES[mes - 1]}-{str(anio)[2:]}",
        "dato_hasta": ultimo.date(), "dia": dia, "dias_mes": dias_mes, "fuente": fuente,
        "cerrado": cerrado, "confiabilidad": confiabilidad, "peso_curva": peso_curva,
        "sin_meta_canal": sin_meta_canal,
        "excluidos": excl, "excluido_mm": excluido_mm,
        "venta_acum": venta_acum, "share_ly": share, "rec_acum": rec_acum_tot,
        "punt_acum": venta_acum - rec_acum_tot,
        "venta_proy": venta_proy, "venta_lineal": venta_lineal,
        "mgd_pct": 1 - costo_acum / venta_acum if venta_acum else 0,
        "mc_pct": mc_proy / venta_proy if venta_proy else 0, "mc_proy": mc_proy, "mc_acum": mc_acum,
        "gav": gav_proy, "ebitda_proy": ebitda_proy,
        "md_proy": md_proy, "md_acum": md_acum,
        "md_prev_pct": (fe_prev["MD"] / fe_prev["Venta"]) if fe_prev["Venta"] else None,
        "mc_prev_pct": (fe_prev["Contribución"] / fe_prev["Venta"]) if fe_prev["Venta"] else None,
        "seguimiento": seg, "estacionalidad": est,
        "meta": meta, "fcst": {"Venta": fcst_venta, "Contribución": fcst_mc}, "ppto": ppto_mes,
        "da": da_proy, "operaciones": operaciones, "factor_cont": factor_cont,
        "pct_venta": venta_proy / meta["Venta"] if meta["Venta"] else None,
        "gap_ebitda": gap_ebitda, "semaforo": semaforo, "calibracion": cal,
        "lineas": lineas, "negocios": negocios, "desv_negocio": [d for d in negocios if abs(d[3]) >= 1],
        "desviaciones": desv, "diario": diario.to_dict(),
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = proyectar_cierre()
    m = p["meta"]
    print(f"{p['etiqueta']} · fuente {p['fuente']} · dato al {p['dato_hasta']} (día {p['dia']}/{p['dias_mes']}, "
          f"{p['share_ly']*100:.0f}% del mes recurrente LY) · excluidos {len(p['excluidos'])} docs ({p['excluido_mm']:,.1f} MM)")
    print(f"{'Línea':<14}{'acum':>8}{'proy':>8}{'fcst':>8}{'ppto':>8} | {'base%':>6}{'señal':>7}{'punt':>7}{'MC%':>6} regla")
    for l in p["lineas"]:
        sn = f"{l['mc_senal']*100:7.1f}" if l["mc_senal"] is not None else "     — "
        print(f"{l['linea']:<14}{l['acum']:8.1f}{l['proy']:8.1f}{l['fcst_venta']:8.1f}{l['ppto_venta']:8.1f} | "
              f"{l['base_pct']*100:6.1f}{sn}{l['puntual_venta']:7.1f}{l['mc_pct']*100:6.1f} {l['regla']}")
    for o in p["operaciones"]:
        print(f"  puntual {o['documento']:<12}{o['canal']:<16}{o['venta']:7.1f}  mgd {o['mgd']*100:5.1f}  MC {o['mc_pct']*100:5.1f}"
              f" vs base {o['base_pct']*100:5.1f} → impacto {o['impacto']:+6.1f}{' (override)' if o['override'] else ''}")
    print(f"TOTAL venta acum {p['venta_acum']:,.1f} proy {p['venta_proy']:,.1f} meta {m['Venta']:,.1f} "
          f"({p['pct_venta']*100:.0f}%) fcst {p['fcst']['Venta']:,.1f}")
    print(f"MC proy {p['mc_proy']:,.1f} ({p['mc_pct']*100:.1f}%) meta {m['Contribución']:,.1f} fcst {p['fcst']['Contribución']:,.1f} "
          f"| GAV {p['gav']:,.1f} | EBITDA proy {p['ebitda_proy']:,.1f} vs meta {m['EBITDA']:,.1f} → {p['semaforo'].upper()}")
    for c, v, mt, g in p["desviaciones"][:4] + p["desviaciones"][-3:]:
        print(f"   {c:<22} proy {v:7.1f} meta {mt:7.1f} gap {g:+7.1f}")
