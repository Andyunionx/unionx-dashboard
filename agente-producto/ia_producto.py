"""IA del Evaluador de productos v3 (Andrés 11-oct-2026): Claude por API para
  1. ficha()             → ficha técnica estructurada desde la página y sus PDF (manual, ficha, CE), con el nombre del
                           producto como se declara en aduana y la partida probable;
  2. investigar_origen() → dueño de la marca, fábrica (confirmada o candidatas con nivel de evidencia) y costo de origen,
                           con búsqueda web;
  3. rankear()           → similitud de líneas de la DIN contra la ficha (0–100 y por qué).
A la IA SOLO van el link, el texto público de la página y glosas públicas de la DIN: nunca nuestros costos ni márgenes.
Sin ANTHROPIC_API_KEY todo devuelve None y el evaluador sigue con reglas (link_producto.ficha_por_patrones).
Modelos configurables: AGENTE_IA_MODELO (ficha y ranking) y AGENTE_IA_MODELO_INVESTIGA (investigación).
"""
from __future__ import annotations

import json
import os

MODELO = os.environ.get("AGENTE_IA_MODELO", "claude-sonnet-5-5")
MODELO_INVESTIGA = os.environ.get("AGENTE_IA_MODELO_INVESTIGA", "claude-opus-5-5")


def disponible() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _cliente():
    import anthropic
    return anthropic.Anthropic()


def _forzar(modelo: str, sistema: str, contenido: str, herramienta: dict, max_tokens: int = 3000) -> dict | None:
    """Llamada con una herramienta obligatoria: la respuesta es el JSON de su input_schema."""
    r = _cliente().messages.create(model=modelo, max_tokens=max_tokens, system=sistema, tools=[herramienta],
                                   tool_choice={"type": "tool", "name": herramienta["name"]},
                                   messages=[{"role": "user", "content": contenido}])
    for b in r.content:
        if getattr(b, "type", "") == "tool_use":
            return dict(b.input)
    return None


# ── 1) ficha técnica ────────────────────────────────────────────────────────
FICHA = {"name": "ficha_producto", "description": "Ficha técnica estructurada del producto, solo con datos presentes en el texto.",
         "input_schema": {"type": "object", "properties": {
             "nombre": {"type": "string"}, "marca": {"type": "string"},
             "dueno_marca": {"type": "string", "description": "empresa dueña/importadora de la marca si el texto la nombra (razón social, país)"},
             "tipo_producto": {"type": "string", "description": "qué es, genérico y en español (ej. 'espumador de leche eléctrico')"},
             "terminos_aduana": {"type": "array", "items": {"type": "string"},
                                 "description": "3 a 6 palabras en español, MAYÚSCULAS sin tildes, como se declararía en una DIN chilena (ej. ESPUMADOR, LECHE, ELECTRICO)"},
             "partida_probable": {"type": "string", "description": "partida arancelaria chilena probable de 8 dígitos"},
             "unidad_comparacion": {"type": "string", "enum": ["U", "SET", "PAR", "KG"]},
             "contenido_kg": {"type": "number", "description": "contenido neto por unidad en kg si es un producto a granel/alimento (ej. 1 kg)"},
             "precio": {"type": "number"}, "moneda": {"type": "string"},
             "especificaciones": {"type": "object", "properties": {
                 "potencia_w": {"type": "number"}, "capacidad_ml": {"type": "number"}, "voltaje": {"type": "string"},
                 "medidas_mm": {"type": "array", "items": {"type": "number"}}, "peso_kg": {"type": "number"},
                 "materiales": {"type": "array", "items": {"type": "string"}}, "funciones": {"type": "array", "items": {"type": "string"}},
                 "colores": {"type": "array", "items": {"type": "string"}}, "certificaciones": {"type": "array", "items": {"type": "string"}},
                 "otras": {"type": "object", "additionalProperties": {"type": "string"}}}},
             "origen": {"type": "string", "description": "país de fabricación si aparece (ej. 'Made in China')"},
             "fabricante_texto": {"type": "string", "description": "fabricante o modelo de fábrica SOLO si aparece literal en el texto"},
             "modelo_fabrica": {"type": "string"},
             "unidades_por_caja": {"type": "number"}, "medidas_caja_mm": {"type": "array", "items": {"type": "number"}},
             "observaciones": {"type": "string"}},
             "required": ["nombre", "tipo_producto", "terminos_aduana", "unidad_comparacion"]}}


def ficha(link: dict) -> dict | None:
    if not disponible():
        return None
    meta = {k: link.get(k) for k in ("url", "tienda", "nombre", "marca", "precio", "moneda", "sku", "gtin")}
    contenido = (f"Datos estructurados del link: {json.dumps(meta, ensure_ascii=False)}\n\n"
                 f"TEXTO DE LA PÁGINA:\n{(link.get('texto_pagina') or '')[:12000]}\n\n"
                 f"TEXTO DE LOS PDF ENLAZADOS (manual/ficha):\n{(link.get('texto_pdfs') or '')[:15000]}")
    return _forzar(MODELO, "Eres analista de compras de una importadora chilena. Extrae la ficha técnica del producto SOLO con lo que dice "
                           "el texto; si un dato no aparece, omítelo. No inventes fabricantes ni cifras.", contenido, FICHA)


# ── 2) investigación de origen (búsqueda web) ───────────────────────────────
ORIGEN = {"name": "registrar_origen", "description": "Resultado de la investigación de origen y fabricación.",
          "input_schema": {"type": "object", "properties": {
              "dueno_marca": {"type": "string"}, "pais_origen": {"type": "string"},
              "fabricante_confirmado": {"type": "object", "properties": {"nombre": {"type": "string"}, "evidencia": {"type": "string"},
                                                                        "url": {"type": "string"}}},
              "candidatos": {"type": "array", "items": {"type": "object", "properties": {
                  "nombre": {"type": "string"}, "ciudad": {"type": "string"}, "tipo": {"type": "string", "enum": ["fábrica", "trading", "desconocido"]},
                  "modelo": {"type": "string"}, "coincidencia": {"type": "string", "enum": ["alta", "media", "baja"]},
                  "evidencia": {"type": "string"}, "url": {"type": "string"},
                  "fob_min_usd": {"type": "number"}, "fob_max_usd": {"type": "number"}, "moq": {"type": "number"}},
                  "required": ["nombre", "coincidencia", "evidencia"]}},
              "costo_origen_usd": {"type": "object", "properties": {"min": {"type": "number"}, "max": {"type": "number"},
                                                                     "base": {"type": "string"}}},
              "fuentes": {"type": "array", "items": {"type": "string"}}, "notas": {"type": "string"}},
              "required": ["candidatos", "notas"]}}


def investigar_origen(f: dict, url: str | None = None, max_busquedas: int = 8) -> dict | None:
    """Busca en la web quién fabrica el producto (o el diseño equivalente) y a qué costo. Nunca afirma un fabricante sin evidencia."""
    if not disponible():
        return None
    import anthropic
    cli = _cliente()
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_busquedas}, ORIGEN]
    pedido = ("Investiga el ORIGEN y la FABRICACIÓN de este producto para poder cotizarlo directo en China:\n"
              f"{json.dumps(f, ensure_ascii=False)[:6000]}\nLink: {url or '—'}\n\n"
              "Busca: (1) la empresa dueña de la marca y si declara fábrica; (2) manuales, declaraciones CE, certificados o registros que "
              "nombren al fabricante o un modelo de fábrica; (3) el mismo diseño o especificaciones equivalentes en Alibaba, 1688, "
              "Made-in-China o Global Sources, con fábrica, ciudad, modelo, precio FOB y MOQ; (4) registros de importación públicos. "
              "Reglas: no afirmes un fabricante sin evidencia directa (fabricante_confirmado solo si un documento lo nombra); los demás van "
              "como candidatos con coincidencia alta (mismo diseño y especificaciones), media (mismas especificaciones) o baja (similar). "
              "Costo de origen = rango FOB de los candidatos de coincidencia alta/media. Al final llama a registrar_origen.")
    mensajes = [{"role": "user", "content": pedido}]
    for _ in range(6):
        r = cli.messages.create(model=MODELO_INVESTIGA, max_tokens=6000, tools=tools, messages=mensajes,
                                system="Eres un investigador de abastecimiento (sourcing) riguroso. Respondes en español.")
        for b in r.content:
            if getattr(b, "type", "") == "tool_use" and b.name == "registrar_origen":
                out = dict(b.input)
                out["_uso"] = {"entrada": r.usage.input_tokens, "salida": r.usage.output_tokens}
                return out
        mensajes.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "pause_turn":                     # búsqueda larga en el servidor: continuar
            continue
        mensajes.append({"role": "user", "content": "Registra ahora el resultado con registrar_origen."})
    return None


# ── 3) ranking de similitud contra la DIN ───────────────────────────────────
RANK = {"name": "ranking", "description": "Similitud de cada línea de la DIN con el producto.",
        "input_schema": {"type": "object", "properties": {"lineas": {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "similitud": {"type": "integer", "minimum": 0, "maximum": 100}, "razon": {"type": "string"}},
            "required": ["i", "similitud", "razon"]}}}, "required": ["lineas"]}}


def rankear(f: dict, filas: list[dict]) -> dict[int, dict] | None:
    """filas: [{i, glosa, partida, unidad, kg_u, fob_u}] (datos públicos de la DIN). Devuelve {i: {similitud, razon}}."""
    if not disponible() or not filas:
        return None
    contenido = (f"PRODUCTO:\n{json.dumps({k: f.get(k) for k in ('tipo_producto', 'marca', 'especificaciones', 'contenido_kg', 'modelo_fabrica')}, ensure_ascii=False)}\n\n"
                 f"LÍNEAS DE IMPORTACIÓN (Aduana Chile):\n{json.dumps(filas, ensure_ascii=False)}\n\n"
                 "Puntúa de 0 a 100 qué tan parecido es cada línea al PRODUCTO (mismo tipo, misma capacidad/potencia/tamaño, peso por unidad "
                 "comparable, misma marca o modelo = 100). Una razón breve por línea. Devuelve todas las líneas.")
    out = _forzar(MODELO, "Eres analista de comercio exterior. Comparas fichas técnicas con glosas de aduana.", contenido, RANK, 4000)
    return {x["i"]: {"similitud": x["similitud"], "razon": x["razon"]} for x in (out or {}).get("lineas", [])} if out else None
