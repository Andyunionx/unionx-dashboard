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
    a = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("America/Santiago"))
    except Exception:  # noqa: BLE001
        ahora = datetime.now()
    # el cron de GitHub llega 3-4,5 h tarde: la corrida de la mañana se reconoce por el cron que la disparó
    import os
    cron_manana = os.environ.get("ROI_CRON", "") == "0 11 * * 1-5"
    lunes = a.lunes or (ahora.weekday() == 0 and (ahora.hour < 12 or cron_manana))

    import roi_publicar as pub
    fechas = pub.fechas_fuentes()
    previo = pub.estado_guardado()
    cambios = [k for k, v in fechas.items() if previo.get(k) != v]
    hoy = f"{ahora:%Y-%m-%d}"
    if lunes and previo.get("resumen") == hoy and not a.lunes:
        lunes = False                  # el resumen de hoy ya salió (corrida duplicada del cron)
    print(f"[vigía] {ahora:%d-%m %H:%M} · cambios en: {cambios or 'ninguna'} · lunes={lunes} · forzar={a.forzar}")
    if not (a.forzar or lunes or cambios):
        print("[vigía] sin cambios en las maestras: no se recalcula")
        return 0

    import roi_producto as rp
    import roi_supuestos
    sup = roi_supuestos.aplicar_panel(rp)
    try:
        rp.bajar_drive(True)
        s, aud, pools_det, pools, excluidos, meta = rp.calcular(False)
        pr, _, _ = rp.cargar_pricing()
        n_pi = rp.historial_pi()["pi"].nunique()
        hist = pub.leer_historico()
        prev = pub.ultima_corrida(hist, rp.ALCANCE)
        prob = pub.controles(s, prev, len(pr), n_pi)
        if prob:
            raise RuntimeError("Controles de calidad: " + " | ".join(prob))
        conc = rp.conciliacion_eerr(s)
        out = rp.exportar(s, aud, pools_det, pools, excluidos, conc, meta, "_auto")
        print("[roi] Excel:", out)
        if a.sin_subir:
            print("[roi] --sin-subir: fin (no se publica)")
            return 0
        extra = {"alcance": rp.ALCANCE, "ventana": f"{rp.VENTANA_DESDE}/{rp.VENTANA_HASTA}",
                 "publicado": f"{ahora:%Y-%m-%d %H:%M}", "resumen": previo.get("resumen", "")}
        if lunes and not a.sin_enviar:
            extra["resumen"] = hoy
        fid = pub.publicar_excel(out, fechas, extra)
        link = f"https://drive.google.com/file/d/{fid}/view"
        if not a.sin_inyectar:
            r = pub.inyectar_planificacion(s)
            print("[planificación]", r)
        pub.guardar_historico(hist, s, meta)
        if lunes and not a.sin_enviar:
            html = pub.resumen_html(s, prev, meta, link)
            pub.enviar(pub.RESUMEN_TO, f"ROI por producto — resumen semanal {ahora:%d-%m}", html, cc="andres@unionx.cl")
            print("[roi] resumen enviado a", pub.RESUMEN_TO)
        print(f"[roi] OK · cambios {cambios} · supuestos del panel: {len(sup)}")
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if not a.sin_enviar and not a.sin_subir:
            pub.enviar(pub.ALERTA_TO, "⚠️ ROI por producto: no se publicó",
                       f"<p>La actualización automática del ROI no se publicó ({ahora:%d-%m %H:%M}).</p>"
                       f"<p><b>Motivo:</b> {e}</p><p>Cambios detectados en: {cambios or 'ninguna (corrida semanal)'}.</p>"
                       "<p>El Excel y la Planificación quedan con la última versión publicada.</p>")
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
