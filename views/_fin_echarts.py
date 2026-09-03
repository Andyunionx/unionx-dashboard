# -*- coding: utf-8 -*-
"""
Motor de gráficos ECharts para la App Finanzas (dirección "MD Gráficos").

Aplica las reglas pro: etiquetas directas (no leyendas donde se pueda), un solo
color de énfasis + grises, títulos que afirman la conclusión (los pone la vista),
cifras es-CL tabulares, grilla horizontal punteada tenue, sin bordes ni ticks,
animación única que respeta prefers-reduced-motion, y la cascada con base
invisible + altura siempre positiva (fix de barras negativas).

Los labels se precomputan en Python (formato es-CL) para no inyectar funciones JS.
"""
from __future__ import annotations

import json

import streamlit.components.v1 as components

# ---- paleta (branding gerencial + neutros del método) ----
EMF = "#2E75B6"      # único color de énfasis (azul UnionX)
NAVY = "#1F3864"
GRAY = "#B9C6CF"     # serie secundaria
GRAY2 = "#8FA3B0"    # serie terciaria
RULE = "#DCE3E8"     # grilla / ejes
MUTE = "#7C8B98"     # texto de ejes
INK = "#1E293B"
NEG = "#9B3A2F"      # negativo (rojo apagado)
POS = "#0E7A54"      # positivo
POS_SOFT = "#5FA98A"
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif"
MONO = "ui-monospace,'Cascadia Mono',Consolas,'DejaVu Sans Mono',monospace"

_TOKENS = {
    "@@AXIS_NUM@@": "function(v){return fmtNum(v);}",
    "@@TIP@@": "function(p){var q=Array.isArray(p)?p:[p];var s='<b>'+(q[0].name||'')+'</b>';"
               "q.forEach(function(x){if(x.data&&x.data.tip!=null){s+='<br>'+x.data.tip;}"
               "else if(x.value!=null&&x.seriesName&&x.seriesName[0]!=='_'){s+='<br>'+x.seriesName+': '+fmtNum(x.value);}});return s;}",
}


def es(v, dec: int = 0) -> str:
    """Número es-CL: punto de miles, coma decimal, − real."""
    if v is None:
        return "—"
    s = f"{abs(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if v < 0 else "") + s


def render(option: dict, height: int = 360, key: str | None = None):
    opt = json.dumps(option, ensure_ascii=False)
    for tok, js in _TOKENS.items():
        opt = opt.replace(f'"{tok}"', js)
    html = f"""
<div id="ch" style="width:100%;height:{height - 12}px"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js"></script>
<script>
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
function fmtNum(v){{ if(v==null||v==='')return ''; const a=Math.abs(v);
  const d=(a<10&&a!==Math.round(a))?1:0;
  return v.toLocaleString('es-CL',{{minimumFractionDigits:d,maximumFractionDigits:d}}); }}
const el = document.getElementById('ch');
const chart = echarts.init(el);
const opt = {opt};
opt.animation = !reduce; opt.animationDuration = 720; opt.animationEasing = 'cubicOut';
chart.setOption(opt);
new ResizeObserver(() => chart.resize()).observe(el);
</script>"""
    components.html(html, height=height)


# ---- piezas base ----
def _cat_axis(cats, rotate=0):
    return {"type": "category", "data": cats, "axisTick": {"show": False},
            "axisLine": {"lineStyle": {"color": RULE}},
            "axisLabel": {"color": MUTE, "fontFamily": FONT, "fontSize": 11,
                          "interval": 0, "rotate": rotate}}


def _val_axis(unidad=None):
    return {"type": "value", "name": unidad, "nameTextStyle": {"color": MUTE, "fontSize": 10},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": MUTE, "fontFamily": MONO, "fontSize": 10, "formatter": "@@AXIS_NUM@@"},
            "splitLine": {"lineStyle": {"color": RULE, "type": "dashed"}}}


def _tooltip(axis=True):
    return {"trigger": "axis" if axis else "item", "formatter": "@@TIP@@",
            "backgroundColor": "#0F1E28", "borderWidth": 0, "padding": [7, 10],
            "textStyle": {"color": "#fff", "fontSize": 12, "fontFamily": FONT},
            "axisPointer": {"type": "none"}}


def _lbl(texto, pos="top", color=INK, bold=False, size=10):
    return {"show": True, "position": pos, "formatter": texto, "color": color,
            "fontFamily": MONO, "fontSize": size, "fontWeight": "bold" if bold else "normal"}


# ============================================================
# CASCADA (waterfall) — base invisible + altura siempre positiva
# ============================================================
def cascada(steps, base=None, unidad="MM CLP", height=380):
    """steps: [(label, delta, kind)] kind: start | dec | total. base = venta para % interno."""
    cats, bases, alts, tops = [], [], [], []
    cum = 0.0
    for lab, delta, kind in steps:
        cats.append(lab.replace("\n", "\n"))
        if kind == "total":
            b, h, disp = min(0, cum), abs(cum), cum
            color = POS if cum >= 0 else NEG
        elif kind == "start":
            b, h, disp = min(0, delta), abs(delta), delta
            color = EMF
            cum = delta
        else:
            nxt = cum + delta
            b, h, disp = min(cum, nxt), abs(delta), delta
            color = POS_SOFT if delta > 0 else GRAY
            cum = nxt
        bases.append(b)
        pct = (f"{abs(disp) / base * 100:.0f}%" if (base and kind != "total" and base != 0) else "")
        tip = f"{es(disp)} {unidad}" + (f" · {abs(disp)/base*100:.1f}% s/venta".replace(".", ",") if pct else "")
        alts.append({"value": h, "tip": tip,
                     "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
                     "label": _lbl(pct, "inside", "#fff", True) if (pct and base and h > base * 0.045) else {"show": False}})
        signo = "+" if (kind == "dec" and disp > 0) else ""
        tops.append({"value": b + h, "tip": None,
                     "label": _lbl(signo + es(disp), "top",
                                   INK if kind in ("start", "total") else MUTE,
                                   kind in ("start", "total"))})
    return {
        "tooltip": _tooltip(),
        "grid": {"left": 8, "right": 16, "top": 26, "bottom": 6, "containLabel": True},
        "xAxis": _cat_axis(cats),
        "yAxis": _val_axis(unidad),
        "series": [
            {"name": "_base", "type": "bar", "stack": "wf", "data": bases,
             "itemStyle": {"color": "transparent"}, "emphasis": {"disabled": True},
             "tooltip": {"show": False}, "barWidth": "56%"},
            {"name": "valor", "type": "bar", "stack": "wf", "data": alts, "barWidth": "56%"},
            {"name": "_tops", "type": "bar", "data": tops, "barGap": "-100%", "barWidth": "56%",
             "itemStyle": {"color": "transparent"}, "emphasis": {"disabled": True},
             "tooltip": {"show": False}},
        ],
    }


# ============================================================
# BARRAS VERTICALES AGRUPADAS — última serie = énfasis
# ============================================================
def barras(cats, series, unidad="MM CLP", height=340, colores=None, pcts=None):
    """series: [(nombre, [valores])]. La ÚLTIMA serie lleva el énfasis; el resto gris.
    pcts: opcional [(nombre, [str % por punto])] para tooltip."""
    n = len(series)
    if colores is None:
        colores = ([GRAY2, GRAY][:max(0, n - 1)] + [EMF]) if n > 1 else [EMF]
        colores = ([GRAY] * (n - 1) + [EMF])[-n:]
    out = []
    for i, (nombre, vals) in enumerate(series):
        data = []
        for j, v in enumerate(vals):
            extra = f" · {pcts[i][j]}" if (pcts and pcts[i] and pcts[i][j]) else ""
            data.append({"value": v, "tip": f"{nombre}: {es(v)} {unidad}{extra}",
                         "label": _lbl(es(v), "top", INK if i == n - 1 else MUTE, i == n - 1, 9)})
        out.append({"name": nombre, "type": "bar", "data": data,
                    "itemStyle": {"color": colores[i], "borderRadius": [3, 3, 0, 0]},
                    "barMaxWidth": 34})
    return {
        "tooltip": _tooltip(),
        "legend": {"show": n > 1, "top": 0, "right": 4, "itemWidth": 10, "itemHeight": 10,
                   "icon": "roundRect", "textStyle": {"color": MUTE, "fontSize": 11, "fontFamily": FONT}},
        "grid": {"left": 8, "right": 16, "top": 30, "bottom": 6, "containLabel": True},
        "xAxis": _cat_axis(cats),
        "yAxis": _val_axis(unidad),
        "series": out,
    }


# ============================================================
# BARRAS HORIZONTALES — composición con etiqueta directa
# ============================================================
def barras_h(items, unidad="MM CLP", pct=True, height=None, dec=0, color_max=True):
    """items: [(label, valor)] o [(label, valor, color)]. Énfasis en el mayor, resto gris."""
    items = [(it[0], it[1], (it[2] if len(it) > 2 else None)) for it in items if it[1] is not None]
    total = sum(abs(v) for _, v, _ in items) or 1
    vmax = max(abs(v) for _, v, _ in items) if items else 0
    data = []
    for lab, v, col in reversed(items):
        color = col or (EMF if (color_max and abs(v) == vmax) else GRAY)
        share = f" · {abs(v)/total*100:.0f}%" if pct else ""
        data.append({"value": v, "tip": f"{es(v, dec)} {unidad}{share}",
                     "itemStyle": {"color": color, "borderRadius": [0, 3, 3, 0]},
                     "label": _lbl(es(v, dec) + share, "right", INK, abs(v) == vmax, 10)})
    labs = [lab for lab, _, _ in reversed(items)]
    return {
        "tooltip": _tooltip(False),
        "grid": {"left": 8, "right": 90, "top": 8, "bottom": 4, "containLabel": True},
        "xAxis": {**_val_axis(), "splitLine": {"lineStyle": {"color": RULE, "type": "dashed"}}},
        "yAxis": {"type": "category", "data": labs, "axisTick": {"show": False},
                  "axisLine": {"show": False},
                  "axisLabel": {"color": INK, "fontFamily": FONT, "fontSize": 11.5}},
        "series": [{"type": "bar", "data": data, "barMaxWidth": 22}],
    }


# ============================================================
# LÍNEA(S) DE EVOLUCIÓN — etiqueta directa al final, sin leyenda
# ============================================================
def linea(fechas, series, unidad="MM CLP", height=320, area=True, ref=None, banda=None):
    """series: [(nombre, [valores])]. 1a serie énfasis, resto gris. endLabel directo.
    ref: (label, y) línea horizontal punteada de referencia.
    banda: (lo, hi, label) franja horizontal sombreada (ej. rango de mercado)."""
    out = []
    for i, (nombre, vals) in enumerate(series):
        color = EMF if i == 0 else (GRAY2 if i == 1 else GRAY)
        s = {"name": nombre, "type": "line", "data": [round(v, 1) if v is not None else None for v in vals],
             "symbol": "none", "lineStyle": {"color": color, "width": 2.4},
             "itemStyle": {"color": color},
             "endLabel": {"show": True, "formatter": nombre, "color": color,
                          "fontFamily": FONT, "fontSize": 11, "fontWeight": "bold", "distance": 8},
             "labelLayout": {"moveOverlap": "shiftY"}}
        if area and i == 0 and len(series) == 1:
            s["areaStyle"] = {"color": EMF, "opacity": 0.08}
        out.append(s)
    if ref:
        rlab, ry = ref
        out[0]["markLine"] = {
            "symbol": "none", "silent": True,
            "lineStyle": {"color": NAVY, "type": "dashed", "width": 1.4},
            "label": {"formatter": f"{rlab} {es(ry, 1)}", "color": NAVY, "fontFamily": MONO,
                      "fontSize": 10, "position": "insideEndTop", "rotate": 0},
            "data": [{"yAxis": ry}]}
    if banda:
        lo, hi, blab = banda
        out[0]["markArea"] = {
            "silent": True, "itemStyle": {"color": GRAY, "opacity": 0.14},
            "label": {"show": True, "formatter": blab, "color": MUTE, "fontFamily": FONT,
                      "fontSize": 10, "position": "insideBottomRight"},
            "data": [[{"yAxis": lo}, {"yAxis": hi}]]}
    return {
        "tooltip": {**_tooltip(), "axisPointer": {"type": "line", "lineStyle": {"color": RULE}}},
        "grid": {"left": 8, "right": 96, "top": 14, "bottom": 6, "containLabel": True},
        "xAxis": {**_cat_axis(fechas), "boundaryGap": False,
                  "axisLabel": {"color": MUTE, "fontFamily": FONT, "fontSize": 10, "interval": "auto", "rotate": 0}},
        # las líneas no necesitan base cero (regla 5) — scale ajusta el rango al dato
        "yAxis": {**_val_axis(unidad), "scale": True},
        "series": out,
    }


# ============================================================
# BARRAS (apiladas u agrupadas) + LÍNEA de referencia — un solo eje
# ============================================================
def barras_linea(cats, barras, linea_ref=None, unidad="MM CLP", stack=True):
    """barras: [(nombre, vals, color)] · linea_ref: (nombre, vals) línea punteada de referencia."""
    series = []
    for nombre, vals, color in barras:
        data = [{"value": (round(v, 1) if v is not None else None),
                 "tip": f"{nombre}: {es(v)} {unidad}" if v is not None else None} for v in vals]
        series.append({"name": nombre, "type": "bar", "data": data,
                       "stack": "b" if stack else None,
                       "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
                       "barMaxWidth": 30})
    if linea_ref:
        nombre, vals = linea_ref
        series.append({"name": nombre, "type": "line",
                       "data": [round(v, 1) if v is not None else None for v in vals],
                       "symbol": "circle", "symbolSize": 5,
                       "lineStyle": {"color": NAVY, "width": 2, "type": "dashed"},
                       "itemStyle": {"color": NAVY},
                       "endLabel": {"show": True, "formatter": nombre, "color": NAVY,
                                    "fontFamily": FONT, "fontSize": 11, "fontWeight": "bold", "distance": 8}})
    return {
        "tooltip": _tooltip(),
        "legend": {"show": True, "top": 0, "right": 4, "itemWidth": 10, "itemHeight": 10,
                   "icon": "roundRect", "textStyle": {"color": MUTE, "fontSize": 11, "fontFamily": FONT}},
        "grid": {"left": 8, "right": 96, "top": 30, "bottom": 6, "containLabel": True},
        "xAxis": _cat_axis(cats),
        "yAxis": _val_axis(unidad),
        "series": series,
    }


# ============================================================
# RANGOS HORIZONTALES (football field) — base invisible + rango
# ============================================================
def rango_h(items, unidad="MM CLP", height=None):
    """items: [(nombre, lo, hi)] — barra de rango lo→hi con etiqueta directa."""
    items = [it for it in items if it[1] is not None and it[2] is not None]
    labs = [n for n, _, _ in reversed(items)]
    bases = [lo for _, lo, _ in reversed(items)]
    rangos = []
    for n, lo, hi in reversed(items):
        rangos.append({"value": hi - lo, "tip": f"{es(lo)} – {es(hi)} {unidad}",
                       "itemStyle": {"color": EMF, "opacity": 0.75, "borderRadius": 3},
                       "label": _lbl(f"{es(lo)} – {es(hi)}", "right", INK, False, 10)})
    return {
        "tooltip": _tooltip(False),
        "grid": {"left": 8, "right": 120, "top": 10, "bottom": 4, "containLabel": True},
        "xAxis": {**_val_axis(unidad), "splitLine": {"lineStyle": {"color": RULE, "type": "dashed"}}},
        "yAxis": {"type": "category", "data": labs, "axisTick": {"show": False},
                  "axisLine": {"show": False},
                  "axisLabel": {"color": INK, "fontFamily": FONT, "fontSize": 11.5}},
        "series": [
            {"type": "bar", "stack": "r", "data": bases, "itemStyle": {"color": "transparent"},
             "emphasis": {"disabled": True}, "tooltip": {"show": False}, "barMaxWidth": 20},
            {"type": "bar", "stack": "r", "data": rangos, "barMaxWidth": 20},
        ],
    }


# ============================================================
# HISTOGRAMA (Monte Carlo) — con mediana anotada
# ============================================================
def histograma(valores, bins=40, mediana=None, unidad="MM CLP", height=330):
    import numpy as np
    hist, edges = np.histogram([v for v in valores], bins=bins)
    cats = [es((edges[i] + edges[i + 1]) / 2) for i in range(len(hist))]
    data = [{"value": int(h), "tip": f"{int(h)} escenarios"} for h in hist]
    opt = {
        "tooltip": _tooltip(False),
        "grid": {"left": 8, "right": 16, "top": 30, "bottom": 6, "containLabel": True},
        "xAxis": {**_cat_axis(cats), "axisLabel": {"color": MUTE, "fontFamily": MONO, "fontSize": 9, "interval": max(1, bins // 8)}},
        "yAxis": {**_val_axis("escenarios")},
        "series": [{"type": "bar", "data": data, "barCategoryGap": "12%",
                    "itemStyle": {"color": EMF, "opacity": 0.85, "borderRadius": [2, 2, 0, 0]}}],
    }
    if mediana is not None:
        import bisect
        ix = max(0, min(len(cats) - 1, bisect.bisect_left(list(edges[1:]), mediana)))
        opt["series"][0]["markLine"] = {
            "symbol": "none", "lineStyle": {"color": NAVY, "type": "dashed", "width": 1.6},
            "label": {"formatter": f"P50 {es(mediana)}", "color": NAVY, "fontFamily": MONO,
                      "fontSize": 10, "position": "end", "rotate": 0},
            "data": [{"xAxis": ix}]}
    return opt
