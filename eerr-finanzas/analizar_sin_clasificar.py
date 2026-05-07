"""
Analiza los movimientos sin clasificación para identificar patrones
y crear nuevas reglas
"""

import json
from collections import defaultdict
from pathlib import Path

def analizar_sin_clasificar():
    """Lee el JSON clasificado y analiza los sin clasificar"""

    ruta_json = "02 EE.RR Febrero 2026_CLASIFICADO.json"

    if not Path(ruta_json).exists():
        print(f"Error: {ruta_json} no encontrado")
        return

    with open(ruta_json, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    # Filtrar sin clasificación
    sin_clasificar = [d for d in datos if not d['clasificacion']['ln']]

    print("\n" + "="*80)
    print(f"ANÁLISIS: {len(sin_clasificar)} MOVIMIENTOS SIN CLASIFICAR")
    print("="*80)

    # Agrupar por código
    por_codigo = defaultdict(list)
    for item in sin_clasificar:
        codigo = item['codigo']
        por_codigo[codigo].append(item)

    # Mostrar resumen por código
    print(f"\nRESUMEN POR CÓDIGO ({len(por_codigo)} códigos únicos):\n")

    codigos_sorted = sorted(por_codigo.items(),
                           key=lambda x: sum(m['saldo'] for m in x[1]),
                           reverse=True)

    total_monto = 0
    for codigo, movimientos in codigos_sorted:
        cantidad = len(movimientos)
        monto_total = sum(m['saldo'] for m in movimientos)
        total_monto += monto_total

        print(f"\n{codigo} ({cantidad} movimientos | M$ {monto_total:,.2f})")

        # Mostrar glosas únicas
        glosas = {}
        for mov in movimientos:
            glosa = mov['glosa'] or "(sin glosa)"
            if glosa not in glosas:
                glosas[glosa] = 0
            glosas[glosa] += 1

        # Top 3 glosas
        top_glosas = sorted(glosas.items(), key=lambda x: x[1], reverse=True)[:3]
        for glosa, count in top_glosas:
            print(f"    - {glosa[:60]:60s} ({count}x)")

        # Mostrar contraparte más común
        contraparte_map = {}
        for mov in movimientos:
            contra = mov['contraparte'] or "(sin contraparte)"
            if contra not in contraparte_map:
                contraparte_map[contra] = 0
            contraparte_map[contra] += 1

        top_contra = sorted(contraparte_map.items(), key=lambda x: x[1], reverse=True)[0]
        print(f"    Contraparte: {top_contra[0][:40]} ({top_contra[1]}x)")

    print(f"\n{'='*80}")
    print(f"TOTAL SIN CLASIFICAR: M$ {total_monto:,.2f}")
    print(f"{'='*80}")

    # Generar sugerencias de reglas
    print(f"\n\nSUGERENCIAS DE NUEVAS REGLAS:\n")
    print("Basadas en patrones de glosa y contraparte:\n")

    for codigo, movimientos in codigos_sorted[:15]:  # Top 15
        print(f"\n# Código {codigo}")

        # Detectar patrones
        glosas_unicas = set(m['glosa'] for m in movimientos if m['glosa'])
        contras_unicas = set(m['contraparte'] for m in movimientos if m['contraparte'])

        # Sugerir línea de negocio basado en contexto
        suggested_ln = "UNION X"  # Default
        suggested_cc = "GASTOS GENERALES"

        # Heurística simple basada en código
        if codigo.startswith("41"):
            suggested_ln = "UNION X"
            suggested_cc = "INGRESOS"
        elif codigo.startswith("42"):
            suggested_ln = "UNION X"
            suggested_cc = "GASTOS"
        elif codigo.startswith("43"):
            suggested_ln = "GRUPO ETER"
            suggested_cc = "GASTOS"
        elif codigo.startswith("44"):
            suggested_ln = "NO SE CONSIDERA"
            suggested_cc = ""

        # Si hay patrón en glosa
        glosa_sample = list(glosas_unicas)[0] if glosas_unicas else ""

        if any(word in glosa_sample.upper() for word in ["REMUNERACION", "SUELDO"]):
            suggested_cc = "REMUNERACIONES"
        elif any(word in glosa_sample.upper() for word in ["MARKETING", "PUBLICIDAD", "ADS"]):
            suggested_cc = "MARKETING"
        elif any(word in glosa_sample.upper() for word in ["SUSCRIPCION", "SOFTWARE"]):
            suggested_cc = "SUSCRIPCIONES"

        # Generar regla
        print(f'  {{"codigo":"{codigo}","campo":"NINGUNO","keyword":"","ln":"{suggested_ln}","cc":"{suggested_cc}","area2":"","sa":"","ca":""}}')

        # O con glosa
        if glosa_sample:
            keyword = glosa_sample.split()[0]
            print(f'  {{"codigo":"{codigo}","campo":"GLOSA","keyword":"{keyword}","ln":"{suggested_ln}","cc":"{suggested_cc}","area2":"","sa":"","ca":""}}')

if __name__ == "__main__":
    analizar_sin_clasificar()
