"""
Vista Presupuesto vs Real — App Finanzas.
Dos modalidades claras (tabs):
  1. P&L Drive — Real (FCST) vs Presupuesto (PPTO) del Sheet de gestión (Gabriela),
     con apertura del gasto por área (dónde se ahorró / se pasó).
  2. Metas 2026 — cumplimiento por KPI vs meta y vs año anterior.
"""
import pandas as pd
import streamlit as st

from views import _fin_planilla as P
from views import _fin_ui as UI


def render():
    with st.sidebar:
        st.markdown("### 💵 **Presupuesto vs Real**")
        st.caption("P&L Drive · Metas 2026")
        st.divider()

    st.title("💵 Presupuesto vs Real")
    st.caption("Ejecución presupuestaria · P&L de gestión (Drive) y Metas 2026 · MM CLP")

    tab1, tab2 = st.tabs(["📊 P&L vs Presupuesto (Drive)", "🎯 Metas 2026"])

    # ════════════════ TAB 1 — P&L Drive ════════════════
    with tab1:
        periodos = P.drive_periodos()
        if not periodos:
            st.warning("⏳ Sin datos del P&L Drive (`control_gestion.parquet`).")
        else:
            year, month, modo = UI.selector_periodo(periodos, key="pre_drive", con_modo=True)
            acum = modo != "Mes"
            etiqueta = (f"Ene–{P.MESES[month-1]} {year}" if acum else P.label_mes(year, month))
            pl = P.drive_pl(year, month, acumulado=acum)

            def _real(k): return pl.get(k, {}).get("real")
            def _ppto(k): return pl.get(k, {}).get("ppto")
            def _cumpl(k):
                p, r = _ppto(k), _real(k)
                return (r / p * 100) if (p and r is not None and p != 0) else None

            st.markdown(f"### 📌 {etiqueta}")
            c = st.columns(4)
            for i, (k, nombre) in enumerate([("venta", "Venta"), ("contribucion", "Contribución"),
                                             ("gav", "GAV"), ("ebit", "EBIT")]):
                r, p = _real(k), _ppto(k)
                cu = _cumpl(k)
                # para gasto, cumplir presupuesto = gastar ≤ presupuesto (menor es mejor)
                if k == "gav":
                    color = UI.GOOD if (cu is not None and cu <= 100) else UI.BAD
                    meta_txt = f"Ppto {P.fmt_mm(p)} · {f'{cu:.0f}% del ppto' if cu is not None else '—'}"
                else:
                    color = UI.GOOD if (cu and cu >= 100) else (UI.AMBER if (cu and cu >= 90) else UI.BAD)
                    meta_txt = f"Ppto {P.fmt_mm(p)} · {f'{cu:.0f}% cumpl.' if cu is not None else '—'}"
                UI.kpi(c[i], nombre, P.fmt_mm(r), meta_txt, color if cu is not None else UI.INK)

            # Tabla P&L Real vs Ppto
            st.markdown("#### Estado de resultados — Real vs Presupuesto")
            vr = _real("venta"); vp = _ppto("venta")
            filas = []
            for k, nombre in [("venta", "Venta"), ("contribucion", "Margen de contribución"),
                              ("gav", "(−) GAV"), ("ebit", "EBIT")]:
                r, p = _real(k), _ppto(k)
                filas.append({
                    "Línea": nombre,
                    "Presupuesto": P.fmt_mm(p),
                    "Real": P.fmt_mm(r),
                    "Δ": P.fmt_mm((r or 0) - (p or 0)),
                    "%": (f"{(r/p-1)*100:+.1f}%".replace(".", ",") if (p and r is not None) else "—"),
                    "% s/venta": (P.fmt_pct_venta(r, vr) if k != "venta" else "100,0%"),
                })
            st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

            UI.barras_agrupadas(
                ["Venta", "Contribución", "GAV", "EBIT"],
                {"Presupuesto": [_ppto(k) for k in ("venta", "contribucion", "gav", "ebit")],
                 "Real": [_real(k) for k in ("venta", "contribucion", "gav", "ebit")]},
                f"Real vs Presupuesto — {etiqueta} (MM CLP)")

            # Detalle del gasto por área
            st.markdown("#### Detalle del gasto — dónde se ahorró / se pasó")
            g = P.drive_gasto(year, month, acumulado=acum, by=("linea_negocio", "area"))
            if not g.empty:
                disp = pd.DataFrame({
                    "Línea negocio": g["linea_negocio"],
                    "Área": g["area"].replace("", "—"),
                    "Presupuesto": g["Ppto"].map(lambda v: P.fmt_mm(v)),
                    "Real": g["Real"].map(lambda v: P.fmt_mm(v)),
                    "Ahorro (+) / sobregasto (−)": g["ahorro"].map(lambda v: P.fmt_mm(v)),
                    "Desvío %": g["pct"].map(lambda v: f"{v:+.0f}%" if pd.notna(v) else "—"),
                })
                st.dataframe(disp, width="stretch", hide_index=True)
                tot_ah = g["ahorro"].sum()
                st.info(f"**Gasto total: {P.fmt_mm_md(g['Real'].sum())} vs presupuesto {P.fmt_mm_md(g['Ppto'].sum())} "
                        f"→ {'ahorro' if tot_ah>=0 else 'sobregasto'} de {P.fmt_mm_md(abs(tot_ah))}.** "
                        "Δ positivo = gastó menos que el presupuesto.")
            st.caption("Fuente: P&L Drive de gestión (Sheet de Gabriela) → `control_gestion.parquet`. "
                       "FCST = real acumulado; PPTO = presupuesto.")

    # ════════════════ TAB 2 — Metas 2026 ════════════════
    with tab2:
        mperiodos = P.metas_periodos()
        if not mperiodos:
            st.warning("⏳ Sin datos de metas.")
        else:
            my, mm, mmodo = UI.selector_periodo(mperiodos, key="pre_metas", con_modo=True)
            macum = mmodo != "Mes"
            metiq = (f"Ene–{P.MESES[mm-1]} {my}" if macum else P.label_mes(my, mm))
            res = P.metas_resumen(my, mm, acumulado=macum)

            st.markdown(f"### 📌 {metiq}")
            cols = st.columns(len(P.METAS_KPIS))
            for i, kpi in enumerate(P.METAS_KPIS):
                d = res.get(kpi, {})
                meta, real = d.get("Meta"), d.get("Resultado")
                cumpl = (real / meta * 100) if (meta and real is not None) else None
                color = UI.GOOD if (cumpl and cumpl >= 100) else (UI.AMBER if (cumpl and cumpl >= 90) else UI.BAD)
                UI.kpi(cols[i], kpi, P.fmt_mm(real),
                       f"Meta {P.fmt_mm(meta)} · {f'{cumpl:.0f}%' if cumpl is not None else '—'}",
                       color if cumpl is not None else UI.INK)

            st.markdown("#### Meta vs Real vs Año anterior")
            filas = []
            for kpi in P.METAS_KPIS:
                d = res.get(kpi, {})
                meta, real, r25 = d.get("Meta"), d.get("Resultado"), d.get("Resultado 2025")
                filas.append({
                    "KPI": kpi, "Meta": P.fmt_mm(meta), "Real": P.fmt_mm(real),
                    "% Cumpl.": (f"{real/meta*100:.0f}%" if (meta and real is not None) else "—"),
                    f"{my-1}": P.fmt_mm(r25), "YoY": P.fmt_var(P.yoy(real, r25)),
                })
            st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

            UI.barras_agrupadas(
                P.METAS_KPIS,
                {"Meta": [res.get(k, {}).get("Meta") for k in P.METAS_KPIS],
                 "Año ant.": [res.get(k, {}).get("Resultado 2025") for k in P.METAS_KPIS],
                 "Real": [res.get(k, {}).get("Resultado") for k in P.METAS_KPIS]},
                f"Meta vs Real vs Año anterior — {metiq} (MM CLP)")

            # Detalle mensual como en la planilla
            st.markdown("#### Detalle mensual — como en la planilla Metas 2026")
            kpi_sel = st.selectbox("KPI", P.METAS_KPIS, key="pre_metas_grid")
            grid = P.metas_grid(kpi_sel, my)
            if not grid.empty:
                mss = [m for m in range(1, 13) if m in grid.columns]

                def _s(tipo):
                    return {m: (grid.loc[tipo, m] if tipo in grid.index else None) for m in mss}

                meta_s, real_s, r25_s = _s("Meta"), _s("Resultado"), _s("Resultado 2025")

                def _row(label, s, fmt="mm", base=None):
                    row = {"Concepto": label}
                    tot = 0.0
                    for m in mss:
                        v = s.get(m)
                        if fmt == "mm":
                            row[P.MESES[m - 1]] = P.fmt_mm(v) if pd.notna(v) else "—"
                            tot += v if pd.notna(v) else 0
                        else:
                            bv = base.get(m)
                            row[P.MESES[m - 1]] = (f"{(v/bv-1)*100:+.0f}%" if (pd.notna(v) and bv) else "—")
                    row["Año"] = P.fmt_mm(tot) if fmt == "mm" else ""
                    return row

                st.dataframe(pd.DataFrame([
                    _row("Meta", meta_s), _row("Real", real_s),
                    _row("Δ vs Meta", real_s, "pct", meta_s),
                    _row("Real 2025", r25_s), _row("YoY", real_s, "pct", r25_s),
                ]), width="stretch", hide_index=True)

            st.caption("Fuente: Planificación Financiera 2026 · hoja Metas 2026.")
