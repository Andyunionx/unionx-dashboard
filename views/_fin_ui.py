"""
Helpers de UI compartidos para las vistas de Planificación Financiera.
KPIs (.fin-kpi), selector de período, y gráficos ECharts (dirección "MD Gráficos"):
etiquetas directas, un solo color de énfasis, cifras es-CL, grilla tenue.
"""
from __future__ import annotations

import streamlit as st

try:
    from views import _fin_planilla as P
    from views import _fin_echarts as ECH
except ImportError:
    import _fin_planilla as P
    import _fin_echarts as ECH

# Branding gerencial UnionX
BLUE = "#2E75B6"
NAVY = "#1F3864"
TEAL = "#0E7490"
SLATE = "#94A3B8"
SLATEL = "#C7D9EC"
GOOD = "#0E7A54"
BAD = "#C0392B"
AMBER = "#B45309"
INK = "#1E293B"
GREEN2 = "#5FA98A"


# ---------------- KPI cards ----------------
def kpi_html(label: str, valor: str, meta: str = "", color: str = INK) -> str:
    return f"""<div class="fin-kpi">
        <div class="label">{label}</div>
        <div class="valor" style="color:{color};">{valor}</div>
        <div class="meta">{meta}</div>
    </div>"""


def kpi(col, label, valor, meta="", color=INK):
    col.markdown(kpi_html(label, valor, meta, color), unsafe_allow_html=True)


def color_umbral(v, bueno, malo, invertido=False):
    if v is None:
        return SLATE
    if invertido:
        return GOOD if v <= bueno else (AMBER if v <= malo else BAD)
    return GOOD if v >= bueno else (AMBER if v >= malo else BAD)


# ---------------- selector de período ----------------
def selector_periodo(periodos: list[tuple[int, int]], key: str, con_modo: bool = False,
                     default_real: bool = True):
    """Filtro Año + Mes en el ÁREA PRINCIPAL. Default = último mes real (mes −1).
    Devuelve (year, month) o (year, month, modo) si con_modo=True.
    """
    if not periodos:
        return (None, None, None) if con_modo else (None, None)
    years = sorted({y for y, _ in periodos})
    dy, dm = P.ultimo_mes_real(periodos) if default_real else periodos[-1]
    widths = [1, 1, 1.6, 3] if con_modo else [1, 1, 4]
    cols = st.columns(widths)
    with cols[0]:
        y = st.selectbox("Año", years, index=years.index(dy) if dy in years else len(years) - 1,
                         key=f"{key}_y")
    months = sorted(m for yy, m in periodos if yy == y)
    dmv = dm if (y == dy and dm in months) else months[-1]
    with cols[1]:
        m = st.selectbox("Mes", months, index=months.index(dmv),
                         format_func=lambda mm: P.MESES[mm - 1], key=f"{key}_m")
    if con_modo:
        with cols[2]:
            modo = st.radio("Vista", ["Mes", "Acumulado (YTD)"], horizontal=True, key=f"{key}_modo")
        return y, m, modo
    return y, m


# ---------------- Gráficos (ECharts, renderizan directo) ----------------
def titulo_grafico(t: str, sub: str = ""):
    if not t:
        return
    st.markdown(
        f"<div style='color:{NAVY};font-weight:700;font-size:14.5px;margin:10px 0 0'>{t}</div>"
        + (f"<div style='color:#7C8B98;font-size:11.5px'>{sub}</div>" if sub else ""),
        unsafe_allow_html=True)


def waterfall_pl(pl: dict, titulo="", alto=380):
    """Cascada Venta → Costo → Comisiones → GAV → RNO → Utilidad (renderiza)."""
    venta = pl.get("venta") or 0
    steps = [
        ("Venta", venta, "start"),
        ("Costo directo", -abs(pl.get("costo") or 0), "dec"),
        ("Comis. + var.", -abs(pl.get("comisiones") or 0), "dec"),
        ("GAV", -abs(pl.get("gav") or 0), "dec"),
        ("RNO", -abs(pl.get("rno") or 0), "dec"),
        ("Utilidad", 0, "total"),
    ]
    titulo_grafico(titulo)
    ECH.render(ECH.cascada(steps, base=venta), height=alto)


def cascada_libre(steps, titulo="", base=None, alto=360):
    """Cascada genérica (ej. puente EV → Patrimonio). steps: [(label, delta, kind)]."""
    titulo_grafico(titulo)
    ECH.render(ECH.cascada(steps, base=base), height=alto)


def barh_composicion(items, titulo="", pct=True, colores=None, alto=None, dec=0):
    """Barras horizontales de composición, etiqueta directa valor + % (renderiza)."""
    items = [(l, v) for l, v in items if v is not None]
    if colores:
        items = [(l, v, colores[i % len(colores)]) for i, (l, v) in enumerate(items)]
    titulo_grafico(titulo)
    ECH.render(ECH.barras_h(items, pct=pct, dec=dec, color_max=not colores),
               height=alto or (70 + 40 * len(items)))


def barras_agrupadas(cats, series: dict, titulo="", colores=None, alto=340, pcts=None):
    """Barras agrupadas: series = {nombre: [valores]}. Última serie = énfasis (renderiza)."""
    ser = list(series.items())
    titulo_grafico(titulo)
    ECH.render(ECH.barras(cats, ser, colores=colores, pcts=pcts), height=alto)


def linea_evolucion(fechas, series, titulo="", unidad="MM CLP", alto=320, ref=None, banda=None):
    """Líneas de evolución con etiqueta directa al final (renderiza).
    series: {nombre: [valores]} o [(nombre, valores)].
    ref: (label, y) línea de referencia · banda: (lo, hi, label) franja sombreada."""
    ser = list(series.items()) if isinstance(series, dict) else list(series)
    titulo_grafico(titulo)
    ECH.render(ECH.linea(fechas, ser, unidad=unidad, ref=ref, banda=banda), height=alto)


def puente_yoy(cur: dict, prev: dict, lbl_prev: str, lbl_cur: str, titulo="", alto=360):
    """Puente de variación de la utilidad vs año anterior (cascada de deltas).
    Identidad del Fcst EERR: utilidad = venta + costo + comisiones − gav + rno
    (costo/comisiones vienen negativos; gav normalizado positivo)."""
    u_p, u_c = prev.get("utilidad"), cur.get("utilidad")
    if u_p is None or u_c is None:
        return

    def d(k, signo=1):
        return signo * ((cur.get(k) or 0) - (prev.get(k) or 0))

    steps = [(f"Utilidad\n{lbl_prev}", u_p, "start"),
             ("Δ Venta", d("venta"), "dec"),
             ("Δ Costo directo", d("costo"), "dec"),
             ("Δ Comis. + var.", d("comisiones"), "dec"),
             ("Δ GAV", d("gav", -1), "dec"),
             ("Δ RNO", d("rno"), "dec")]
    resid = u_c - (u_p + sum(s[1] for s in steps[1:]))
    if abs(resid) > 0.5:
        steps.append(("Otros", resid, "dec"))
    steps.append((f"Utilidad\n{lbl_cur}", 0, "total"))
    titulo_grafico(titulo)
    ECH.render(ECH.cascada(steps), height=alto)


def histograma_mc(valores, mediana=None, titulo="", alto=330):
    titulo_grafico(titulo)
    ECH.render(ECH.histograma(list(valores), mediana=mediana), height=alto)


def rango_metodos(items, titulo="", alto=None):
    """Football field: [(nombre, lo, hi)] (renderiza)."""
    titulo_grafico(titulo)
    ECH.render(ECH.rango_h(items), height=alto or (70 + 44 * len(items)))
