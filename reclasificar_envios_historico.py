# -*- coding: utf-8 -*-
"""
Reclasifica los ENVÍOS (despachos) del histórico congelado para que NO caigan bajo
tipo_compra='Compra' (proveedores nacionales). Los envíos no tienen proveedor, por
lo que inflaban el margen directo de proveedores nacionales (~77% vs ~39% real).

tipo_compra -> 'Envío' donde es_despacho (o marca 'Despachos' / sku 'Delivery*').
Forward ya lo hace mejoras_raw_overlay.py (P5c); esto arregla el congelado.

Uso:  python reclasificar_envios_historico.py           # dry-run
      python reclasificar_envios_historico.py --apply   # aplica (backup .bak_envio)
"""
import argparse, shutil
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
HIST = ROOT / "data" / "historico" / "ventas_historico.parquet"


def es_envio(df):
    m = pd.Series(False, index=df.index)
    if "es_despacho" in df.columns:
        m |= df["es_despacho"].fillna(False).astype(bool)
    m |= df["marca"].astype(str).str.strip().str.lower().eq("despachos")
    m |= df["sku"].astype(str).str.startswith("Delivery")
    return m


def main(apply=False):
    h = pd.read_parquet(HIST)
    env = es_envio(h)
    tc = h["tipo_compra"].astype(str).str.strip()
    cambia = env & tc.str.lower().ne("envío")
    print(f"[hist] filas envío: {int(env.sum()):,} | tipo_compra antes: "
          f"{h.loc[env, 'tipo_compra'].astype(str).value_counts().to_dict()}")
    print(f"[hist] a reclasificar -> 'Envío': {int(cambia.sum()):,} filas "
          f"(${h.loc[cambia, 'venta_bruta'].astype(float).sum()/1e6:.1f}M venta bruta)")

    # sanity: proveedores nacionales (Compra) antes/después
    comp = h["tipo_compra"].astype(str).str.strip().str.lower().eq("compra")
    vb_comp_antes = h.loc[comp, "venta_bruta"].astype(float).sum()
    mg_comp_antes = h.loc[comp, "margen_front"].astype(float).sum()
    print(f"[Compra] ANTES: venta ${vb_comp_antes/1e6:.1f}M · margen ${mg_comp_antes/1e6:.1f}M "
          f"· {mg_comp_antes/(vb_comp_antes/1.19)*100:.1f}% (s/neta)")

    h.loc[cambia, "tipo_compra"] = "Envío"

    comp2 = h["tipo_compra"].astype(str).str.strip().str.lower().eq("compra")
    vb2 = h.loc[comp2, "venta_bruta"].astype(float).sum()
    mg2 = h.loc[comp2, "margen_front"].astype(float).sum()
    print(f"[Compra] DESPUÉS: venta ${vb2/1e6:.1f}M · margen ${mg2/1e6:.1f}M "
          f"· {mg2/(vb2/1.19)*100:.1f}% (s/neta)")

    if not apply:
        print("\n[DRY-RUN] no se escribió nada.")
        return
    shutil.copy2(str(HIST), str(HIST) + ".bak_envio")
    h.to_parquet(HIST, index=False, compression="zstd")
    print(f"\n[OK] aplicado. Backup .bak_envio  ({len(h):,} filas)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    main(**vars(ap.parse_args()))
