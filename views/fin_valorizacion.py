"""
Vista Valorización — App Finanzas.
Varios métodos de valorización con simulación:
  · DCF (FCFF) — flujo de caja libre descontado, interactivo
  · Múltiplos de mercado — EV/EBITDA, EV/Ventas, P/E
  · Simulación Monte Carlo — distribución del valor variando supuestos
  · Resumen — comparación de métodos (football field)
Reemplaza la Valorización de la planilla (que está rota).
"""
import numpy as np
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def _dcf(ebit0, tax, g_exp, reinv, years, wacc, g_term, net_debt):
    if wacc <= g_term:
        return None
    pv = 0.0
    e = ebit0
    fcff_last = 0.0
    fcffs = []
    for t in range(1, years + 1):
        e *= (1 + g_exp)
        nopat = e * (1 - tax)
        fcff = nopat * (1 - reinv)
        pv += fcff / (1 + wacc) ** t
        fcff_last = fcff
        fcffs.append((e, nopat, fcff, fcff / (1 + wacc) ** t))
    pv_tv = (fcff_last * (1 + g_term) / (wacc - g_term)) / (1 + wacc) ** years
    ev = pv + pv_tv
    return ev, ev - net_debt, pv, pv_tv, fcffs


def _value_box(titulo, valor, sub, color="#2E75B6", ink=False):
    bg = "#fff" if ink else f"linear-gradient(135deg,#1F3864,{color})"
    fg = color if ink else "#fff"
    subc = "#64748B" if ink else "#cfe0f3"
    border = f"border:1px solid #E2E8F0;border-left:5px solid {color};" if ink else ""
    return f"""<div style="flex:1;background:{bg};{border}color:{'#1E293B' if ink else '#fff'};border-radius:14px;padding:18px 22px">
      <div style="font-size:12px;letter-spacing:.05em;color:{subc};text-transform:uppercase">{titulo}</div>
      <div style="font-size:30px;font-weight:800;line-height:1.1;margin-top:4px;color:{fg}">{valor}</div>
      <div style="font-size:12px;color:{subc};margin-top:4px">{sub}</div></div>"""


def render():
    with st.sidebar:
        st.markdown("### 💎 **Valorización**")
        st.caption("DCF · Múltiplos · Simulación")
        st.divider()

    st.title("💎 Valorización de la Empresa")
    st.caption("¿Cuánto vale UnionX? Varios métodos + simulación · MM CLP")

    # ─── Base financiera compartida ─────────────────────────
    fy = P.pl_rango(2026, 1, 12)
    ebit0 = fy.get("ebit") or 0
    ebitda0 = fy.get("ebitda") or 0
    venta0 = fy.get("venta") or 0
    util0 = fy.get("utilidad") or 0
    by, bm = P.ultimo_mes_real(P.balance_periodos())
    b = P.balance_mes(by, bm)
    net_debt = (b.get("deuda_fin") or 0) - (b.get("caja") or 0)
    patrimonio = b.get("patrimonio") or 0

    st.markdown(f"<div style='font-size:12.5px;color:#64748B'>Base FY2026: EBIT {P.fmt_mm(ebit0)} · "
                f"EBITDA {P.fmt_mm(ebitda0)} · Venta {P.fmt_mm(venta0)} · Utilidad {P.fmt_mm(util0)} · "
                f"Deuda neta {P.fmt_mm(net_debt)} · Patrimonio contable {P.fmt_mm(patrimonio)}</div>",
                unsafe_allow_html=True)

    t_dcf, t_mult, t_sim, t_res = st.tabs(["📉 DCF (FCFF)", "✖️ Múltiplos", "🎲 Simulación", "📊 Resumen"])

    # ════════════════ DCF ════════════════
    with t_dcf:
        c = st.columns(3)
        wacc = c[0].slider("WACC (%)", 8.0, 20.0, 12.0, 0.5, key="v_wacc") / 100
        g_exp = c[1].slider("Crecimiento EBIT (%)", 0.0, 15.0, 5.0, 0.5, key="v_gexp") / 100
        g_term = c[2].slider("Crecimiento perpetuo (%)", 0.0, 5.0, 3.0, 0.25, key="v_gter") / 100
        c2 = st.columns(3)
        tax = c2[0].slider("Impuesto (%)", 0.0, 35.0, 27.0, 1.0, key="v_tax") / 100
        reinv = c2[1].slider("Reinversión (%)", 0.0, 60.0, 30.0, 5.0, key="v_reinv") / 100
        years = c2[2].slider("Años", 3, 10, 5, key="v_years")

        r = _dcf(ebit0, tax, g_exp, reinv, years, wacc, g_term, net_debt)
        if not r:
            st.error("El WACC debe ser mayor que el crecimiento perpetuo.")
        else:
            ev, eq, pv_f, pv_tv, fcffs = r
            eq_color = UI.GOOD if eq >= 0 else UI.BAD
            st.markdown(f"<div style='display:flex;gap:16px;margin:8px 0'>"
                        + _value_box("Valor de la Empresa (EV)", P.fmt_mm(ev),
                                     f"{ev/ebitda0:.1f}× EBITDA · VP flujos + terminal".replace(".", ","))
                        + _value_box("Valor del Patrimonio", P.fmt_mm(eq),
                                     f"EV − deuda neta {P.fmt_mm(net_debt)}", eq_color, ink=True)
                        + "</div>", unsafe_allow_html=True)
            if eq < 0:
                st.warning(f"Patrimonio negativo: la deuda neta ({P.fmt_mm_md(net_debt)}) supera el EV ({P.fmt_mm_md(ev)}) "
                           "con estos supuestos (efecto del apalancamiento). Sube crecimiento o baja WACC.")
            UI.cascada_libre([
                ("VP flujos", pv_f, "start"),
                ("VP terminal", pv_tv, "dec"),
                ("Valor Empresa", 0, "total"),
                ("(−) Deuda neta", -net_debt, "dec"),
                ("Valor Patrimonio", 0, "total"),
            ], "Puente Valor Empresa → Patrimonio (MM CLP)", alto=340)
            with st.expander("Proyección de flujo de caja libre (FCFF)"):
                st.dataframe(pd.DataFrame([{"Año": f"Año {i+1}", "EBIT": P.fmt_mm(e), "NOPAT": P.fmt_mm(n),
                                           "FCFF": P.fmt_mm(f), "FCFF desc.": P.fmt_mm(d)}
                                          for i, (e, n, f, d) in enumerate(fcffs)]),
                             width="stretch", hide_index=True)

    # ════════════════ Múltiplos ════════════════
    with t_mult:
        st.caption("Valoración por múltiplos de mercado — ajusta los múltiplos a tu comparable.")
        c = st.columns(3)
        m_ebitda = c[0].slider("EV / EBITDA (×)", 2.0, 12.0, 6.0, 0.5, key="m_ebitda")
        m_ventas = c[1].slider("EV / Ventas (×)", 0.2, 3.0, 1.0, 0.1, key="m_ventas")
        m_pe = c[2].slider("P / E (×)", 4.0, 25.0, 10.0, 1.0, key="m_pe")

        rows = [
            ("EV / EBITDA", f"{m_ebitda:.1f}×".replace(".", ","), P.fmt_mm(ebitda0),
             m_ebitda * ebitda0, m_ebitda * ebitda0 - net_debt),
            ("EV / Ventas", f"{m_ventas:.1f}×".replace(".", ","), P.fmt_mm(venta0),
             m_ventas * venta0, m_ventas * venta0 - net_debt),
            ("P / E (patrimonio)", f"{m_pe:.0f}×", P.fmt_mm(util0),
             m_pe * util0 + net_debt if util0 > 0 else None, m_pe * util0 if util0 > 0 else None),
        ]
        st.dataframe(pd.DataFrame([{
            "Método": n, "Múltiplo": mu, "Base": base,
            "Valor Empresa (EV)": P.fmt_mm(ev) if ev is not None else "—",
            "Valor Patrimonio": P.fmt_mm(eq) if eq is not None else "—",
        } for n, mu, base, ev, eq in rows]), width="stretch", hide_index=True)
        st.info("**EV/EBITDA** y **EV/Ventas** valoran la empresa (EV) y se resta la deuda neta para el patrimonio. "
                "**P/E** valora directamente el patrimonio (múltiplo × utilidad). Ajusta los múltiplos según comparables del sector.")

    # ════════════════ Simulación Monte Carlo ════════════════
    with t_sim:
        st.caption("Simulación Monte Carlo sobre el DCF — muestrea los supuestos y genera la distribución del valor.")
        c = st.columns(4)
        wacc_r = c[0].slider("WACC rango (%)", 8.0, 20.0, (10.0, 14.0), 0.5, key="s_wacc")
        gexp_r = c[1].slider("Crecimiento EBIT rango (%)", 0.0, 15.0, (3.0, 8.0), 0.5, key="s_gexp")
        gter_r = c[2].slider("Crec. perpetuo rango (%)", 0.0, 5.0, (2.0, 3.5), 0.25, key="s_gter")
        n_sim = c[3].select_slider("N simulaciones", [1000, 2500, 5000, 10000], value=5000, key="s_n")
        reinv_s = st.slider("Reinversión (%)", 0.0, 60.0, 30.0, 5.0, key="s_reinv") / 100

        rng = np.random.default_rng(42)
        wc = rng.uniform(wacc_r[0], wacc_r[1], n_sim) / 100
        ge = rng.uniform(gexp_r[0], gexp_r[1], n_sim) / 100
        gt = rng.uniform(gter_r[0], gter_r[1], n_sim) / 100
        evs, eqs = [], []
        for i in range(n_sim):
            if wc[i] <= gt[i]:
                continue
            res = _dcf(ebit0, 0.27, ge[i], reinv_s, 5, wc[i], gt[i], net_debt)
            if res:
                evs.append(res[0]); eqs.append(res[1])
        evs = np.array(evs); eqs = np.array(eqs)
        if len(evs):
            p = lambda a, q: float(np.percentile(a, q))
            k = st.columns(3)
            UI.kpi(k[0], "EV — mediana (P50)", P.fmt_mm(p(evs, 50)),
                   f"P10 {P.fmt_mm(p(evs,10))} · P90 {P.fmt_mm(p(evs,90))}", UI.NAVY)
            UI.kpi(k[1], "Patrimonio — mediana (P50)", P.fmt_mm(p(eqs, 50)),
                   f"P10 {P.fmt_mm(p(eqs,10))} · P90 {P.fmt_mm(p(eqs,90))}",
                   UI.GOOD if p(eqs, 50) >= 0 else UI.BAD)
            UI.kpi(k[2], "Prob. patrimonio > 0", f"{(eqs>0).mean()*100:.0f}%",
                   f"{len(evs):,} simulaciones válidas".replace(",", "."), UI.BLUE)
            UI.histograma_mc(evs.tolist(), mediana=p(evs, 50),
                             titulo="Distribución del Valor de Empresa (MM CLP)", alto=330)
        else:
            st.warning("Ningún escenario válido (WACC siempre ≤ crecimiento perpetuo). Ajusta los rangos.")

    # ════════════════ Resumen ════════════════
    with t_res:
        st.caption("Rango de valor de empresa (EV) por método — para triangular cuánto vale.")
        dcf_r = _dcf(ebit0, 0.27, 0.05, 0.30, 5, 0.12, 0.03, net_debt)
        dcf_lo = _dcf(ebit0, 0.27, 0.03, 0.30, 5, 0.14, 0.025, net_debt)
        dcf_hi = _dcf(ebit0, 0.27, 0.08, 0.30, 5, 0.10, 0.035, net_debt)
        metodos = [
            ("DCF (WACC 10–14%)", dcf_lo[0] if dcf_lo else None, dcf_hi[0] if dcf_hi else None),
            ("EV/EBITDA (5–8×)", 5 * ebitda0, 8 * ebitda0),
            ("EV/Ventas (0,8–1,2×)", 0.8 * venta0, 1.2 * venta0),
        ]
        UI.rango_metodos([(n, lo, hi) for n, lo, hi in metodos if lo is not None],
                         "Los tres métodos convergen en un rango (MM CLP)")
        st.dataframe(pd.DataFrame([{
            "Método": n, "EV mínimo": P.fmt_mm(lo), "EV máximo": P.fmt_mm(hi),
            "Patrimonio (mín–máx)": f"{P.fmt_mm(lo-net_debt)} – {P.fmt_mm(hi-net_debt)}",
        } for n, lo, hi in metodos if lo is not None]), width="stretch", hide_index=True)

    st.caption(f"Base a {P.label_mes(by, bm)}. Modelos simplificados y editables — reemplazan la Valorización "
               "de la planilla (que está rota).")
