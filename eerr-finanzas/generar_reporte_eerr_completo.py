"""
Genera reporte HTML del EERR clasificado con funcionalidades similares a PL_Manager
Incluye desglose de cuentas SPLIT y elementos que requieren trabajo manual
"""

import json
from pathlib import Path
from collections import defaultdict

def generar_reporte_eerr_html(json_path: str, output_path: str = "EERR_Reporte_Interactivo.html"):
    """
    Genera reporte HTML interactivo del EERR clasificado
    """

    # Cargar datos clasificados
    with open(json_path, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    # Agrupar por lnea de negocio y centro de costos
    por_ln = defaultdict(lambda: defaultdict(list))
    split_accounts = []
    estadisticas = {
        "total_movimientos": 0,
        "total_monto": 0,
        "por_ln": defaultdict(lambda: {"cantidad": 0, "monto": 0}),
        "split": {"cantidad": 0, "monto": 0}
    }

    for fila in datos:
        cls = fila.get('clasificacion', {})
        ln = cls.get('ln', 'SIN CLASIFICAR')
        cc = cls.get('cc', 'SIN CENTRO')
        ca = cls.get('ca', '')
        saldo = fila.get('saldo', 0)

        estadisticas["total_movimientos"] += 1
        estadisticas["total_monto"] += saldo

        if ln == "__SPLIT__":
            split_accounts.append(fila)
            estadisticas["split"]["cantidad"] += 1
            estadisticas["split"]["monto"] += saldo
        else:
            por_ln[ln][cc].append(fila)
            estadisticas["por_ln"][ln]["cantidad"] += 1
            estadisticas["por_ln"][ln]["monto"] += saldo

    # Comenzar HTML
    html = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EERR Clasificado - Febrero 2026</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #0F2140 0%, #1B5EA6 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .header p { opacity: 0.9; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f8f9fa;
            border-bottom: 2px solid #e0e0e0;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            border-left: 5px solid #1B5EA6;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .stat-card h3 { color: #1B5EA6; font-size: 12px; margin-bottom: 10px; }
        .stat-card .valor { font-size: 24px; font-weight: bold; color: #0F2140; }
        .stat-card .subtitulo { font-size: 11px; color: #666; margin-top: 5px; }
        .tabs {
            display: flex;
            background: #f0f0f0;
            border-bottom: 2px solid #ddd;
        }
        .tab-btn {
            flex: 1;
            padding: 15px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            color: #666;
            transition: all 0.3s;
        }
        .tab-btn.active {
            background: white;
            color: #0F2140;
            border-bottom: 3px solid #1B5EA6;
        }
        .tab-btn:hover { color: #0F2140; }
        .tab-content { padding: 30px; }
        .tab-content.hidden { display: none; }
        .ln-section { margin-bottom: 30px; }
        .ln-header {
            background: #E8F4F8;
            padding: 15px 20px;
            border-left: 5px solid #1B5EA6;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .ln-header:hover { background: #D0E8F2; }
        .cc-section {
            background: white;
            padding: 15px 20px;
            border-left: 3px solid #90CAF9;
            margin-top: 5px;
            display: none;
        }
        .cc-section.expanded { display: block; }
        .cc-header {
            font-weight: 600;
            color: #1B5EA6;
            padding: 10px 0;
            border-bottom: 1px solid #e0e0e0;
            cursor: pointer;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 13px;
        }
        th {
            background: #0F2140;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: 600;
        }
        td {
            padding: 8px 10px;
            border-bottom: 1px solid #f0f0f0;
        }
        tr:hover { background: #f9f9f9; }
        .monto-positivo { color: #27AE60; font-weight: 600; }
        .monto-negativo { color: #E74C3C; font-weight: 600; }
        .alerta-box {
            background: #FEF2F2;
            border-left: 5px solid #E74C3C;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
        }
        .alerta-box h3 { color: #E74C3C; margin-bottom: 10px; }
        .alerta-item {
            background: white;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 3px solid #FFC107;
        }
        .split-section {
            background: #FFFBEB;
            border-left: 5px solid #FFA500;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
        }
        .split-section h3 { color: #FF8C00; margin-bottom: 15px; }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-ge { background: #E8F5EE; color: #27AE60; }
        .badge-ux { background: #FFFBEB; color: #FF9800; }
        .badge-nc { background: #FEF2F2; color: #E74C3C; }
        .footer {
            background: #f0f0f0;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #666;
            border-top: 1px solid #ddd;
        }
        .toggle-arrow {
            display: inline-block;
            transition: transform 0.3s;
        }
        .toggle-arrow.expanded { transform: rotate(180deg); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>EERR Clasificado - Febrero 2026</h1>
            <p>Estado de Resultados con clasificacion automtica por lnea de negocio y centro de costos</p>
        </div>

        <div class="stats-grid">
"""

    # Agregar estadsticas
    ge_data = estadisticas["por_ln"]["GRUPO ETER"]
    ux_data = estadisticas["por_ln"]["UNION X"]
    nc_data = estadisticas["por_ln"]["NO SE CONSIDERA"]

    html += f"""
            <div class="stat-card">
                <h3>Total Movimientos</h3>
                <div class="valor">{estadisticas["total_movimientos"]}</div>
                <div class="subtitulo">registros procesados</div>
            </div>
            <div class="stat-card">
                <h3>Total Monto</h3>
                <div class="valor">M$ {estadisticas["total_monto"]:,.2f}</div>
                <div class="subtitulo">miles de pesos</div>
            </div>
            <div class="stat-card">
                <h3>GRUPO ETER</h3>
                <div class="valor">{ge_data['cantidad']}</div>
                <div class="subtitulo">M$ {ge_data['monto']:,.2f}</div>
            </div>
            <div class="stat-card">
                <h3>UNION X</h3>
                <div class="valor">{ux_data['cantidad']}</div>
                <div class="subtitulo">M$ {ux_data['monto']:,.2f}</div>
            </div>
            <div class="stat-card">
                <h3>NO SE CONSIDERA</h3>
                <div class="valor">{nc_data['cantidad']}</div>
                <div class="subtitulo">M$ {nc_data['monto']:,.2f}</div>
            </div>
            <div class="stat-card">
                <h3>PENDIENTE SPLIT</h3>
                <div class="valor">{estadisticas["split"]["cantidad"]}</div>
                <div class="subtitulo">M$ {estadisticas["split"]["monto"]:,.2f}</div>
            </div>
        </div>

        <div class="tabs">
            <button class="tab-btn active" onclick="mostrarTab('clasificacion')">CLASIFICACION</button>
            <button class="tab-btn" onclick="mostrarTab('split')">PENDIENTES MANUAL</button>
            <button class="tab-btn" onclick="mostrarTab('detalles')">DETALLES</button>
        </div>

        <div id="clasificacion" class="tab-content">
"""

    # SECCION CLASIFICACION
    for ln in ["GRUPO ETER", "UNION X", "NO SE CONSIDERA"]:
        if ln not in por_ln or not por_ln[ln]:
            continue

        ln_total = estadisticas["por_ln"][ln]["monto"]
        ln_cantidad = estadisticas["por_ln"][ln]["cantidad"]

        if ln == "GRUPO ETER":
            badge_class = "badge-ge"
            color_ln = "#27AE60"
        elif ln == "UNION X":
            badge_class = "badge-ux"
            color_ln = "#FF9800"
        else:
            badge_class = "badge-nc"
            color_ln = "#E74C3C"

        html += f"""
            <div class="ln-section">
                <div class="ln-header" onclick="toggleLN(this)">
                    <span>
                        <span class="badge {badge_class}">{ln}</span>
                        {ln_cantidad} movimientos | M$ {ln_total:,.2f}
                    </span>
                    <span class="toggle-arrow" style="color: {color_ln};"></span>
                </div>
"""

        for cc in sorted(por_ln[ln].keys()):
            movimientos = por_ln[ln][cc]
            cc_monto = sum(m['saldo'] for m in movimientos)
            cc_cantidad = len(movimientos)

            html += f"""
                <div class="cc-section expanded">
                    <div class="cc-header" onclick="toggleCC(event)">
                        {cc} ({cc_cantidad} mov | M$ {cc_monto:,.2f})
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 60px;">#</th>
                                <th style="width: 120px;">Cdigo</th>
                                <th style="width: 200px;">Glosa</th>
                                <th style="width: 150px;">Contraparte</th>
                                <th style="width: 120px;">Monto M$</th>
                                <th style="width: 150px;">Cuenta Analtica</th>
                            </tr>
                        </thead>
                        <tbody>
"""

            for mov in movimientos:
                saldo = mov['saldo']
                clase_monto = "monto-positivo" if saldo >= 0 else "monto-negativo"
                glosa = mov.get('glosa', '')[:50]
                contraparte = mov.get('contraparte', '')[:30]
                ca = mov['clasificacion'].get('ca', '')

                html += f"""
                            <tr>
                                <td>{mov['num_fila']}</td>
                                <td><strong>{mov['codigo']}</strong></td>
                                <td>{glosa}</td>
                                <td style="font-size: 12px; color: #666;">{contraparte}</td>
                                <td class="{clase_monto}">{saldo:,.2f}</td>
                                <td style="font-size: 12px;">{ca}</td>
                            </tr>
"""

            html += """
                        </tbody>
                    </table>
                </div>
"""

        html += """
            </div>
"""

    # SECCION SPLIT - PENDIENTES DE DISTRIBUCION MANUAL
    html += """
        </div>

        <div id="split" class="tab-content hidden">
"""

    if split_accounts:
        html += """
            <div class="alerta-box">
                <h3>Cuentas que Requieren Distribucion Manual</h3>
                <p>Los siguientes movimientos deben ser distribuidos manualmente en las lneas de negocio correspondientes.</p>
            </div>
"""

        # Agrupar split por codigo
        split_por_codigo = defaultdict(list)
        for mov in split_accounts:
            codigo = mov['codigo']
            split_por_codigo[codigo].append(mov)

        for codigo in sorted(split_por_codigo.keys()):
            movimientos = split_por_codigo[codigo]
            total_split = sum(m['saldo'] for m in movimientos)
            cc = movimientos[0]['clasificacion'].get('cc', 'SIN CC')

            html += f"""
            <div class="split-section">
                <h3>Cdigo {codigo} - {cc} (M$ {total_split:,.2f})</h3>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 60px;">#</th>
                            <th style="width: 120px;">Cdigo</th>
                            <th style="width: 250px;">Glosa</th>
                            <th style="width: 150px;">Contraparte</th>
                            <th style="width: 100px;">Monto M$</th>
                            <th style="width: 150px;">Distribuir a:</th>
                        </tr>
                    </thead>
                    <tbody>
"""

            for mov in movimientos:
                saldo = mov['saldo']
                glosa = mov.get('glosa', '')
                contraparte = mov.get('contraparte', '')

                html += f"""
                        <tr>
                            <td>{mov['num_fila']}</td>
                            <td><strong>{mov['codigo']}</strong></td>
                            <td>{glosa}</td>
                            <td style="font-size: 12px;">{contraparte}</td>
                            <td style="color: #FF9800; font-weight: 600;">{saldo:,.2f}</td>
                            <td>
                                <select style="padding: 5px; border-radius: 3px; border: 1px solid #ddd;">
                                    <option value="">-- Seleccionar --</option>
                                    <option value="GRUPO_ETER">GRUPO ETER</option>
                                    <option value="UNION_X">UNION X</option>
                                    <option value="NO_CONSIDERA">NO SE CONSIDERA</option>
                                </select>
                            </td>
                        </tr>
"""

            html += """
                    </tbody>
                </table>
            </div>
"""
    else:
        html += """
            <div class="alerta-box" style="background: #E8F5EE; border-left-color: #27AE60;">
                <h3 style="color: #27AE60;">Perfecto!</h3>
                <p>No hay cuentas pendientes de distribucion manual. Todos los movimientos han sido clasificados.</p>
            </div>
"""

    # SECCION DETALLES
    html += """
        </div>

        <div id="detalles" class="tab-content hidden">
            <h2>Resumen por Centro de Costos</h2>
            <table style="margin-top: 20px;">
                <thead>
                    <tr>
                        <th>Lnea Negocio</th>
                        <th>Centro Costos</th>
                        <th>Cantidad</th>
                        <th>Monto Total</th>
                        <th>% del Total</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Detalles por CC
    todas_lineas = defaultdict(lambda: defaultdict(lambda: {"cant": 0, "monto": 0}))
    for ln in por_ln:
        for cc in por_ln[ln]:
            for mov in por_ln[ln][cc]:
                todas_lineas[ln][cc]["cant"] += 1
                todas_lineas[ln][cc]["monto"] += mov['saldo']

    total_general = estadisticas["total_monto"]
    for ln in sorted(todas_lineas.keys()):
        for cc in sorted(todas_lineas[ln].keys()):
            datos = todas_lineas[ln][cc]
            porcentaje = (datos["monto"] / total_general * 100) if total_general != 0 else 0
            badge = f"badge-{'ge' if ln == 'GRUPO ETER' else 'ux' if ln == 'UNION X' else 'nc'}"
            html += f"""
                    <tr>
                        <td><span class="badge {badge}">{ln}</span></td>
                        <td>{cc}</td>
                        <td style="text-align: center;">{datos['cant']}</td>
                        <td style="text-align: right; font-weight: 600;">{datos['monto']:,.2f}</td>
                        <td style="text-align: right;">{porcentaje:.1f}%</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>Reporte generado automaticamente - EERR Febrero 2026 | Clasificacion con 127 reglas</p>
        </div>
    </div>

    <script>
        function mostrarTab(tabName) {
            const tabs = document.querySelectorAll('.tab-content');
            tabs.forEach(tab => tab.classList.add('hidden'));
            document.getElementById(tabName).classList.remove('hidden');
            const btns = document.querySelectorAll('.tab-btn');
            btns.forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }

        function toggleLN(element) {
            const sections = element.nextElementSibling;
            if (sections) {
                let current = sections.nextElementSibling;
                while (current && current.classList.contains('cc-section')) {
                    current.classList.toggle('expanded');
                    current = current.nextElementSibling;
                }
                element.querySelector('.toggle-arrow').classList.toggle('expanded');
            }
        }

        function toggleCC(event) {
            event.stopPropagation();
            const table = event.target.nextElementSibling;
            if (table) {
                table.style.display = table.style.display === 'none' ? 'table' : 'none';
            }
        }
    </script>
</body>
</html>
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"OK Reporte generado: {output_path}")
    return output_path


if __name__ == "__main__":
    json_path = "02 EE.RR Febrero 2026_CLASIFICADO.json"
    generar_reporte_eerr_html(json_path, "EERR_Reporte_Interactivo.html")
