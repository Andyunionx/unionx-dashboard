"""
ROI por producto automático (Andrés 1-oct-2026).

Corre L-V 08:00 y 14:00 (hora Chile) en GitHub Actions:
  1. Vigía: ¿cambió la Maestra Pricing, la Maestra COMEX o la Maestra Productos desde la última publicación?
     Los lunes a las 08:00 corre igual (venta y stock se mueven aunque las maestras no).
  2. Lee el panel 'Supuestos ROI' (Drive), baja las maestras y calcula (ventana móvil de 12 meses cerrados).
  3. Controles: si algo viene mal, NO publica y avisa solo a Andrés.
  4. Publica: Excel en Drive 'ROI UnionX' · DATAA en la Planificación Forecast 2027 · histórico.
  5. Lunes: resumen por correo (ROI_RESUMEN_TO, CC Andrés).

Uso: python roi_automatico.py [--forzar] [--lunes] [--sin-enviar] [--sin-inyectar] [--sin-subir]
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="calcula aunque las maestras no hayan cambiado")
    ap.add_argument("--lunes", action="store_true", help="corrida semanal: calcula y envía el resumen")
    ap.add_argument("--sin-enviar", action="store_true")
    ap.add_argument("--sin-inyectar", action="store_true", help="no toca la Planificación Forecast 2027")
    ap.add_argument("--sin-subir", action="store_true", help="prueba local: no sube nada a Drive")
    ap.add_argument("--resumen-a", default="", help="prueba: arma el resumen y lo manda SOLO a este correo (no lo marca como enviado)")
    a = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("America/Santiago"))
    except Exception:  # noqa: BLE001
        ahora = datetime.now()
    # el resumen sale en la primera corrida del lunes que termine bien (el cron de GitHub llega 3-4,5 h tarde y,
    # si la de la mañana falla, la de la tarde lo reintenta). El candado "resumen" se pone recién cuando el correo salió.
    lunes = a.lunes or bool(a.resumen_a) or ahora.weekday() == 0

    import roi_publicar as pub
    fechas = pub.reintentar(pub.fechas_fuentes, "leer las fechas de las maestras")
    previo = pub.reintentar(pub.estado_guardado, "leer el estado publicado")
    cambios = [k for k, v in fechas.items() if previo.get(k) != v]
    hoy = f"{ahora:%Y-%m-%d}"
    if lunes and previo.get("resumen") == hoy and not (a.lunes or a.resumen_a):
        lunes = False                  # el resumen de hoy ya salió
    print(f"[vigía] {ahora:%d-%m %H:%M} · cambios en: {cambios or 'ninguna'} · lunes={lunes} · forzar={a.forzar}")
    if not (a.forzar or lunes or cambios):
        print("[vigía] sin cambios en las maestras: no se recalcula")
        return 0

    import roi_producto as rp
    import roi_supuestos
    sup = roi_supuestos.aplicar_panel(rp)
    paso, publicado = "bajar las maestras de Drive", False
    try:
        pub.reintentar(lambda: rp.bajar_drive(True), paso)
        paso = "calcular el ROI"
        s, aud, pools_det, pools, excluidos, meta = rp.calcular(False)
        # exportar() trabaja sobre una copia: el valor del stock al cierre se calcula aquí para el resumen y el histórico
        s["stock_cierre_val"] = s["stock_cierre_u"].clip(lower=0) * s["costo_unit"]
        pr, _, _ = rp.cargar_pricing()
        n_pi = rp.historial_pi()["pi"].nunique()
        paso = "leer el histórico"
        hist = pub.reintentar(pub.leer_historico, paso)
        prev = pub.ultima_corrida(hist, rp.ALCANCE)
        paso = "controles de calidad"
        prob = pub.controles(s, prev, len(pr), n_pi)
        if prob:
            raise RuntimeError("Controles de calidad: " + " | ".join(prob))
        paso = "armar el Excel"
        conc = rp.conciliacion_eerr(s)
        out = rp.exportar(s, aud, pools_det, pools, excluidos, conc, meta, "_auto")
        print("[roi] Excel:", out)
        if a.sin_subir:
            print("[roi] --sin-subir: fin (no se publica)")
            return 0
        extra = {"alcance": rp.ALCANCE, "ventana": f"{rp.VENTANA_DESDE}/{rp.VENTANA_HASTA}",
                 "publicado": f"{ahora:%Y-%m-%d %H:%M}", "resumen": previo.get("resumen", "")}
        # las fechas de las maestras se marcan al final: si un paso falla, la próxima corrida lo vuelve a intentar entero
        paso = "subir el Excel a Drive"
        fid = pub.reintentar(lambda: pub.publicar_excel(out, {k: previo.get(k, "") for k in fechas}, extra), paso)
        publicado = True
        link = f"https://drive.google.com/file/d/{fid}/view"
        if not a.sin_inyectar:
            paso = "inyectar la Planificación Forecast 2027"
            r = pub.reintentar(lambda: pub.inyectar_planificacion(s), paso)
            print("[planificación]", r)
        paso = "guardar el histórico"
        pub.reintentar(lambda: pub.guardar_historico(hist, s, meta), paso)
        pub.reintentar(lambda: pub.marcar(fid, fechas), "marcar las fechas de las maestras")
        if lunes and not a.sin_enviar:
            paso = "armar y enviar el resumen semanal"
            html = pub.resumen_html(s, prev, meta, link)
            to = a.resumen_a or pub.RESUMEN_TO
            pub.reintentar(lambda: pub.enviar(to, f"ROI por producto — resumen semanal {ahora:%d-%m}", html,
                                              cc="" if a.resumen_a else "andres@unionx.cl"), paso, intentos=3)
            print("[roi] resumen enviado a", to)
            if not a.resumen_a:
                pub.reintentar(lambda: pub.marcar(fid, {"resumen": hoy}), "marcar el resumen como enviado")
        print(f"[roi] OK · cambios {cambios} · supuestos del panel: {len(sup)}")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if not a.sin_enviar and not a.sin_subir:
            if not publicado:
                estado = "El Excel y la Planificación quedan con la última versión publicada."
            elif paso.startswith("armar y enviar"):
                estado = "El Excel, la Planificación y el histórico SÍ quedaron actualizados; solo faltó el correo del resumen."
            else:
                estado = "El Excel quedó actualizado en Drive, pero la publicación quedó a medias."
            if pub.transitorio(e):
                sigue = "Fue un error temporal de Google (se reintentó varias veces): la próxima corrida lo vuelve a intentar sola."
            else:
                sigue = "No es un error temporal: la próxima corrida probablemente falle igual. Hay que revisarlo."
            pub.enviar(pub.ALERTA_TO, "⚠️ ROI por producto: " + ("no se publicó" if not publicado else "falló un paso"),
                       f"<p>La actualización automática del ROI falló ({ahora:%d-%m %H:%M}).</p>"
                       f"<p><b>Paso:</b> {paso}<br><b>Motivo:</b> {pub.motivo_corto(e)}</p>"
                       f"<p>{estado} {sigue}</p>"
                       f"<p>Cambios detectados en: {cambios or 'ninguna (corrida semanal)'}.</p>")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
