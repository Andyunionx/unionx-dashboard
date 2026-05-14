"""
Planificador Cyber / Peak Season — calculadora interactiva de dotación.

Sirve para planificar la capacidad operacional en eventos de alta demanda:
Cyber Monday, Black Friday, Día de la Madre, Cyber Day, etc.

Inputs editables:
- Tabla de canales con uds esperadas, % Full Objetivo, modalidad sameday/nextday
- Curva de distribución por día del evento
- Parámetros del equipo (N personas, jornada normal y de evento)
- Costos (horas extras/día, refuerzo/día por persona)

Outputs:
- 3 escenarios costeados:
  A) Solo horas extras del equipo base
  B) Horas extras + refuerzo en días pico
  C) Solo refuerzo sin horas extras (jornada normal)
- Relación costo / venta esperada
- Distribución diaria con detección de brechas
- Recomendación

Carga inicial:
- Productividad observada desde data/capacidad/volumen_operacional_resumen.json
- Headcount actual desde data/ops_manuales/kpis.json
- Datos Cyber pre-cargados (botón "Cargar desde Drive maestro")
"""
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent
DRIVE_FILE_ID_DEFAULT = '1K11y6icDm9M3X3glGUVCOe4HsbpWpEBm'
CREDENTIALS = PROJECT_ROOT / 'credentials.json'

CANALES_SAMEDAY_DEFAULT = (
    'Mercado Libre', 'Falabella', 'Lhotse web', 'Simplit web',
    'UnionX web', 'Walmart', 'Paris',
)

CURVA_DEFAULT = [
    ('Lunes',     30),
    ('Martes',    25),
    ('Miércoles', 20),
    ('Jueves',    12),
    ('Viernes',   8),
    ('Sábado',    5),
]


# ============================================================
# Helpers de carga
# ============================================================
@st.cache_data(ttl=900, show_spinner=False)
def cargar_productividad() -> dict:
    """Productividad observada del equipo (uds/h-persona promedio y P90)."""
    path = PROJECT_ROOT / 'data' / 'capacidad' / 'volumen_operacional_resumen.json'
    if not path.exists():
        return {'uds_por_hpersona_avg': 40.0, 'uds_por_hpersona_p90': 67.0,
                'fuente': 'default (sin parquet)'}
    data = json.load(open(path, encoding='utf-8'))
    ratios = data.get('ratios_equipo', {})
    uds_pp = ratios.get('uds_por_pedido', 3.4)
    avg = ratios.get('pedidos_dia_promedio', 525) * uds_pp
    p90 = ratios.get('pedidos_dia_p90', 877) * uds_pp
    # asumimos jornada normal 9h para derivar uds/h-persona
    h_persona_dia = 5 * 9  # base 5 personas × 9h
    return {
        'uds_por_hpersona_avg': avg / h_persona_dia,
        'uds_por_hpersona_p90': p90 / h_persona_dia,
        'fuente': ratios.get('fuente', '—'),
        'pedidos_dia_avg': ratios.get('pedidos_dia_promedio', 0),
        'pedidos_dia_p90': ratios.get('pedidos_dia_p90', 0),
    }


@st.cache_data(ttl=900, show_spinner=False)
def cargar_headcount_actual() -> int:
    path = PROJECT_ROOT / 'data' / 'ops_manuales' / 'kpis.json'
    if not path.exists():
        return 5
    try:
        data = json.load(open(path, encoding='utf-8'))
        ultimo_mes = sorted(data.get('equipo_bodega', {}).keys())[-1]
        return data['equipo_bodega'][ultimo_mes].get('personas', 5)
    except Exception:
        return 5


def _descargar_drive(file_id: str) -> bytes:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS),
        scopes=['https://www.googleapis.com/auth/drive.readonly'],
    )
    drive = build('drive', 'v3', credentials=creds)
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf.read()


@st.cache_data(ttl=3600, show_spinner="Descargando Drive maestro…")
def cargar_cyber_desde_drive(file_id: str) -> pd.DataFrame:
    """Lee pestaña 'Cyber' del Drive maestro y devuelve DataFrame normalizado."""
    raw = _descargar_drive(file_id)
    df = pd.read_excel(io.BytesIO(raw), sheet_name='Cyber', header=0).head(18)
    df = df.rename(columns={
        'Canal': 'canal', 'Un Cyber': 'uds_total', 'Full Objetivo': 'full_obj',
        'Vta Cyber': 'vta_total',
    })
    df['canal'] = df['canal'].astype(str).str.strip()
    df = df[~df['canal'].str.lower().str.startswith('total')]
    df['uds_total'] = pd.to_numeric(df['uds_total'], errors='coerce').fillna(0).astype(int)
    df['full_obj'] = pd.to_numeric(df['full_obj'], errors='coerce').fillna(0)
    df['vta_total'] = pd.to_numeric(df['vta_total'], errors='coerce').fillna(0).round(0).astype(int)
    df.loc[df['canal'] == 'El Volcan', 'full_obj'] = 1.0
    df['full_obj_pct'] = (df['full_obj'] * 100).round(0).astype(int)
    df['modalidad'] = df['canal'].apply(
        lambda c: 'Sameday' if c in CANALES_SAMEDAY_DEFAULT else 'Nextday',
    )
    return df[['canal', 'modalidad', 'uds_total', 'full_obj_pct', 'vta_total']]


# ============================================================
# Lógica de cálculo
# ============================================================
def calcular_escenarios(df_canal: pd.DataFrame, curva: list,
                         headcount: int, jornada_normal: int, jornada_cyber: int,
                         dias_evento: int, uds_h_avg: float, uds_h_p90: float,
                         costo_he_dia: int, costo_ref_dia: int) -> dict:
    """Devuelve dict con 3 escenarios + métricas globales."""
    df = df_canal.copy()
    df['uds_full'] = (df['uds_total'] * df['full_obj_pct'] / 100).round().astype(int)
    df['uds_equipo'] = df['uds_total'] - df['uds_full']
    df['vta_equipo'] = (df['vta_total'] * (1 - df['full_obj_pct'] / 100)).round(0).astype(int)
    df['vta_full'] = df['vta_total'] - df['vta_equipo']

    uds_total = int(df['uds_equipo'].sum())
    uds_sameday = int(df[df['modalidad'] == 'Sameday']['uds_equipo'].sum())
    uds_nextday = int(df[df['modalidad'] == 'Nextday']['uds_equipo'].sum())
    vta_equipo = int(df['vta_equipo'].sum())
    vta_total = int(df['vta_total'].sum())

    cap_dia_avg_normal = headcount * jornada_normal * uds_h_avg
    cap_dia_avg_cyber = headcount * jornada_cyber * uds_h_avg
    cap_dia_p90_cyber = headcount * jornada_cyber * uds_h_p90

    # Distribución por día
    pct_total = sum(p for _, p in curva)
    if pct_total <= 0:
        pct_total = 100
    distribucion = []
    for nombre, pct in curva:
        uds_dia = uds_total * pct / pct_total
        distribucion.append({'Día': nombre, '% Curva': pct, 'Uds esperadas': round(uds_dia)})

    # Escenario A — solo horas extras (jornada cyber, sin refuerzo)
    rows_A = []
    for d in distribucion:
        uds = d['Uds esperadas']
        rows_A.append({
            'Día': d['Día'], 'Uds esperadas': uds,
            'Cap. avg (13h)': round(cap_dia_avg_cyber),
            'Cap. P90 (13h)': round(cap_dia_p90_cyber),
            'Ritmo necesario': 'P90' if uds > cap_dia_avg_cyber else 'Promedio',
            'Falta vs P90': max(0, round(uds - cap_dia_p90_cyber)),
        })
    costo_A = costo_he_dia * dias_evento

    # Escenario B — HE + refuerzo en días pico
    rows_B = []
    refuerzo_B_dp = 0
    for d in distribucion:
        uds = d['Uds esperadas']
        falta = max(0, uds - cap_dia_avg_cyber)
        if falta > 0:
            uds_por_persona = jornada_cyber * uds_h_avg
            personas = int(falta / uds_por_persona) + (1 if falta % uds_por_persona > 0 else 0)
        else:
            personas = 0
        refuerzo_B_dp += personas
        rows_B.append({
            'Día': d['Día'], 'Uds esperadas': uds,
            'Cap. base (avg)': round(cap_dia_avg_cyber),
            'Personas extra': personas,
            'Cap. con refuerzo': round(cap_dia_avg_cyber + personas * jornada_cyber * uds_h_avg),
        })
    costo_B = costo_he_dia * dias_evento + costo_ref_dia * refuerzo_B_dp

    # Escenario C — solo refuerzo (jornada normal)
    rows_C = []
    refuerzo_C_dp = 0
    for d in distribucion:
        uds = d['Uds esperadas']
        falta = max(0, uds - cap_dia_avg_normal)
        if falta > 0:
            uds_por_persona = jornada_normal * uds_h_avg
            personas = int(falta / uds_por_persona) + (1 if falta % uds_por_persona > 0 else 0)
        else:
            personas = 0
        refuerzo_C_dp += personas
        rows_C.append({
            'Día': d['Día'], 'Uds esperadas': uds,
            'Cap. base (9h avg)': round(cap_dia_avg_normal),
            'Personas extra': personas,
            'Cap. con refuerzo': round(cap_dia_avg_normal + personas * jornada_normal * uds_h_avg),
        })
    costo_C = costo_ref_dia * refuerzo_C_dp

    return {
        'df_canal': df,
        'uds_total': uds_total,
        'uds_sameday': uds_sameday,
        'uds_nextday': uds_nextday,
        'vta_equipo': vta_equipo,
        'vta_total': vta_total,
        'cap_dia_avg_cyber': cap_dia_avg_cyber,
        'cap_dia_p90_cyber': cap_dia_p90_cyber,
        'cap_dia_avg_normal': cap_dia_avg_normal,
        'distribucion': distribucion,
        'A': {'tabla': pd.DataFrame(rows_A), 'costo': costo_A, 'refuerzo_dp': 0},
        'B': {'tabla': pd.DataFrame(rows_B), 'costo': costo_B, 'refuerzo_dp': refuerzo_B_dp},
        'C': {'tabla': pd.DataFrame(rows_C), 'costo': costo_C, 'refuerzo_dp': refuerzo_C_dp},
    }


def generar_excel(esc: dict, params: dict) -> bytes:
    """Reusa la lógica de export del script Excel."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        # Resumen
        resumen = pd.DataFrame([
            ['Volumen total Cyber', f"{int(esc['df_canal']['uds_total'].sum()):,}"],
            ['Uds vía Full Objetivo', f"{int(esc['df_canal']['uds_full'].sum()):,}"],
            ['Uds a cargo del equipo', f"{esc['uds_total']:,}"],
            ['Venta total Cyber', f"$ {esc['vta_total']:,}"],
            ['Venta atribuible al equipo', f"$ {esc['vta_equipo']:,}"],
            ['', ''],
            ['Esc. A: Costo HE solas', f"$ {esc['A']['costo']:,}"],
            ['Esc. B: Costo HE + Refuerzo', f"$ {esc['B']['costo']:,}"],
            ['Esc. C: Costo Solo Refuerzo', f"$ {esc['C']['costo']:,}"],
        ], columns=['Concepto', 'Valor'])
        resumen.to_excel(writer, sheet_name='Resumen', index=False)
        esc['df_canal'].to_excel(writer, sheet_name='Volumen+Venta canal', index=False)
        pd.DataFrame(esc['distribucion']).to_excel(writer, sheet_name='Distribución', index=False)
        esc['A']['tabla'].to_excel(writer, sheet_name='ESC A', index=False)
        esc['B']['tabla'].to_excel(writer, sheet_name='ESC B', index=False)
        esc['C']['tabla'].to_excel(writer, sheet_name='ESC C', index=False)
    buf.seek(0)
    return buf.getvalue()


# ============================================================
# UI
# ============================================================
def render():
    st.title("🎯 Planificador Cyber / Peak Season")
    st.caption(
        "Calculadora interactiva de dotación para eventos de alta demanda "
        "(Cyber, Black Friday, Día de la Madre, etc.)."
    )

    # === Sidebar: parámetros ===
    with st.sidebar:
        st.markdown("### ⚙️ Configuración")

        st.markdown("**Equipo base**")
        headcount = st.number_input("N personas", min_value=1, max_value=50,
                                      value=cargar_headcount_actual(), step=1, key="ocp_hc")
        jornada_normal = st.number_input("Jornada normal (h)", min_value=4, max_value=12,
                                          value=9, step=1, key="ocp_jn")

        st.markdown("**Evento**")
        jornada_cyber = st.number_input("Jornada evento (h)", min_value=8, max_value=16,
                                         value=13, step=1, key="ocp_jc")
        dias_evento = st.number_input("Días de operación", min_value=1, max_value=14,
                                       value=6, step=1, key="ocp_de")

        st.markdown("**Costos (CLP)**")
        costo_he = st.number_input("Horas extras + viáticos / día (todo el equipo)",
                                     min_value=0, value=325000, step=5000, key="ocp_che")
        costo_ref = st.number_input("Refuerzo temporal / día (por persona)",
                                      min_value=0, value=25000, step=5000, key="ocp_cref")

        st.markdown("**Productividad observada**")
        prod = cargar_productividad()
        st.metric("Avg uds/h-persona", f"{prod['uds_por_hpersona_avg']:.1f}")
        st.metric("P90 uds/h-persona", f"{prod['uds_por_hpersona_p90']:.1f}")
        st.caption(f"Fuente: {prod['fuente']}")
        uds_h_avg = st.number_input("Override avg (si querés)",
                                      value=float(prod['uds_por_hpersona_avg']),
                                      step=1.0, key="ocp_uhavg")
        uds_h_p90 = st.number_input("Override P90 (si querés)",
                                      value=float(prod['uds_por_hpersona_p90']),
                                      step=1.0, key="ocp_uhp90")

    # === Sección 1: Datos del evento ===
    st.subheader("1. Datos del evento (unidades por canal)")

    col_carga, col_info = st.columns([1, 2])
    with col_carga:
        if st.button("🔄 Cargar desde Drive maestro", use_container_width=True, type='primary'):
            cargar_cyber_desde_drive.clear()
            try:
                df_loaded = cargar_cyber_desde_drive(DRIVE_FILE_ID_DEFAULT)
                st.session_state['ocp_df_canal'] = df_loaded
                st.success(f"✅ Cargados {len(df_loaded)} canales desde Drive")
            except Exception as e:
                st.error(f"Error: {type(e).__name__}: {str(e)[:120]}")
    with col_info:
        st.caption("Carga la pestaña 'Cyber' del Raw maestro de Ventas. Ajustable manualmente abajo.")

    if 'ocp_df_canal' not in st.session_state:
        # Tabla vacía para input manual
        st.session_state['ocp_df_canal'] = pd.DataFrame(
            columns=['canal', 'modalidad', 'uds_total', 'full_obj_pct', 'vta_total']
        )

    df_canal = st.data_editor(
        st.session_state['ocp_df_canal'],
        num_rows="dynamic",
        use_container_width=True,
        key="ocp_editor",
        column_config={
            'canal': st.column_config.TextColumn('Canal'),
            'modalidad': st.column_config.SelectboxColumn(
                'Modalidad', options=['Sameday', 'Nextday'], required=True),
            'uds_total': st.column_config.NumberColumn('Uds totales', min_value=0, step=1),
            'full_obj_pct': st.column_config.NumberColumn('% Full Obj', min_value=0, max_value=100, step=5),
            'vta_total': st.column_config.NumberColumn('Venta Cyber ($)', min_value=0, step=10000, format='$%d'),
        },
    )

    if df_canal.empty:
        st.info("Cargá datos desde Drive o agregá filas manualmente para ver cálculos.")
        st.stop()

    # === Sección 2: Curva de distribución ===
    st.subheader("2. Curva de distribución diaria")
    curva_df = pd.DataFrame(CURVA_DEFAULT, columns=['Día', '% Curva']).head(dias_evento)
    curva_edit = st.data_editor(
        curva_df, hide_index=True, use_container_width=True, key='ocp_curva',
        column_config={
            'Día': st.column_config.TextColumn('Día'),
            '% Curva': st.column_config.NumberColumn('% del volumen', min_value=0, max_value=100, step=1),
        },
    )
    if abs(curva_edit['% Curva'].sum() - 100) > 1:
        st.warning(f"⚠️ La curva suma {curva_edit['% Curva'].sum()}%. Idealmente debería sumar 100%.")
    curva = list(zip(curva_edit['Día'], curva_edit['% Curva']))

    # === Cálculo ===
    esc = calcular_escenarios(
        df_canal, curva, headcount, jornada_normal, jornada_cyber, dias_evento,
        uds_h_avg, uds_h_p90, costo_he, costo_ref,
    )

    st.divider()

    # === Sección 3: KPIs ===
    st.subheader("3. Volumen y venta")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Uds totales", f"{int(esc['df_canal']['uds_total'].sum()):,}")
    k2.metric("Uds equipo", f"{esc['uds_total']:,}",
              delta=f"{esc['uds_sameday']:,} sameday")
    k3.metric("Venta total Cyber", f"$ {esc['vta_total']/1e6:.1f}M")
    k4.metric("Venta equipo", f"$ {esc['vta_equipo']/1e6:.1f}M")

    # === Sección 4: 3 Escenarios ===
    st.subheader("4. Escenarios de operación")

    e1, e2, e3 = st.columns(3)
    for col, (key, titulo, color) in zip((e1, e2, e3), (
        ('A', 'A) Solo Horas Extras', '#DC2626'),
        ('B', 'B) HE + Refuerzo pico', '#16A34A'),
        ('C', 'C) Solo Refuerzo', '#EA580C'),
    )):
        costo = esc[key]['costo']
        ref = esc[key]['refuerzo_dp']
        pct_vta = costo / esc['vta_equipo'] * 100 if esc['vta_equipo'] else 0
        col.markdown(f"""
        <div style='border-left:4px solid {color};padding:12px;background:#F8FAFC;border-radius:4px;'>
            <div style='font-weight:700;color:{color};font-size:0.95rem;'>{titulo}</div>
            <div style='font-size:1.6rem;font-weight:700;margin:4px 0;'>$ {costo:,.0f}</div>
            <div style='font-size:0.8rem;color:#64748B;'>
                {pct_vta:.2f}% de venta equipo<br>
                {ref} días-persona refuerzo
            </div>
        </div>
        """.replace(',', '.'), unsafe_allow_html=True)

    st.divider()

    # === Sección 5: Detalle por escenario ===
    tab_a, tab_b, tab_c, tab_dist = st.tabs([
        "Esc. A — HE solas", "Esc. B — HE + Refuerzo",
        "Esc. C — Solo refuerzo", "Distribución diaria",
    ])
    with tab_a:
        st.dataframe(esc['A']['tabla'], use_container_width=True, hide_index=True)
        st.caption(f"Costo total: $ {esc['A']['costo']:,}".replace(',', '.'))
    with tab_b:
        st.dataframe(esc['B']['tabla'], use_container_width=True, hide_index=True)
        st.caption(f"Costo total: $ {esc['B']['costo']:,} ({esc['B']['refuerzo_dp']} días-persona refuerzo)".replace(',', '.'))
    with tab_c:
        st.dataframe(esc['C']['tabla'], use_container_width=True, hide_index=True)
        st.caption(f"Costo total: $ {esc['C']['costo']:,} ({esc['C']['refuerzo_dp']} días-persona refuerzo)".replace(',', '.'))
    with tab_dist:
        dist_df = pd.DataFrame(esc['distribucion'])
        dist_df['Cap. avg (Cyber)'] = round(esc['cap_dia_avg_cyber'])
        dist_df['Cap. P90 (Cyber)'] = round(esc['cap_dia_p90_cyber'])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=dist_df['Día'], y=dist_df['Uds esperadas'],
                              name='Uds esperadas', marker_color='#1E40AF'))
        fig.add_trace(go.Scatter(x=dist_df['Día'], y=dist_df['Cap. avg (Cyber)'],
                                  name='Cap. promedio', mode='lines+markers',
                                  line=dict(color='#EA580C', width=2, dash='dash')))
        fig.add_trace(go.Scatter(x=dist_df['Día'], y=dist_df['Cap. P90 (Cyber)'],
                                  name='Cap. P90', mode='lines+markers',
                                  line=dict(color='#16A34A', width=2)))
        fig.update_layout(height=400, paper_bgcolor='rgba(0,0,0,0)',
                          plot_bgcolor='rgba(0,0,0,0)',
                          xaxis_title='Día', yaxis_title='Unidades',
                          showlegend=True, legend=dict(orientation='h', yanchor='bottom', y=1.02))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(dist_df, use_container_width=True, hide_index=True)

    # === Sección 6: Recomendación ===
    st.divider()
    st.subheader("5. Recomendación")
    if esc['A']['costo'] == 0 and esc['B']['costo'] == 0 and esc['C']['costo'] == 0:
        st.info("Sin datos suficientes para recomendar.")
    else:
        ratio_C_A = esc['C']['costo'] / esc['A']['costo'] if esc['A']['costo'] else 0
        if ratio_C_A < 0.3 and esc['C']['refuerzo_dp'] <= 15:
            st.success(
                f"**Recomendación: Escenario C** — $ {esc['C']['costo']:,.0f} CLP "
                f"({esc['C']['costo']/esc['vta_equipo']*100:.2f}% de venta equipo). "
                f"Ahorro vs Esc. A: $ {esc['A']['costo'] - esc['C']['costo']:,.0f}. "
                f"Requiere capacitar {esc['C']['refuerzo_dp']} días-persona de refuerzo."
                .replace(',', '.'))
        else:
            st.info(
                f"**Recomendación: Escenario B** — $ {esc['B']['costo']:,.0f} CLP. "
                f"Equilibra estabilidad (equipo conocido) y eficiencia (refuerzo solo donde hace falta). "
                f"Costo marginal sobre Esc. A: $ {esc['B']['costo'] - esc['A']['costo']:,.0f}."
                .replace(',', '.'))

    # === Sección 7: Export ===
    st.divider()
    xlsx_bytes = generar_excel(esc, {
        'headcount': headcount, 'jornada_cyber': jornada_cyber,
        'dias_evento': dias_evento, 'costo_he': costo_he, 'costo_ref': costo_ref,
    })
    st.download_button(
        "⬇️ Descargar planilla Excel",
        data=xlsx_bytes,
        file_name=f"plan_cyber_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        use_container_width=True,
    )
