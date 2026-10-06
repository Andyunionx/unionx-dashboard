"""Remuneraciones sin detalle personal en los datos que se publican en el repositorio.

El repositorio es PÚBLICO. Regla de Andrés (6-oct-2026): ningún archivo ni app puede mostrar remuneraciones
por persona ni por cargo; en las apps de finanzas solo se ven totales. La nómina con el detalle completo vive
local en su PC, fuera del repo y de Drive.

Lo usan los extractores que escriben datos con centro de costo REMUNERACIONES:
  - extract_finanzas_control_gestion.py   → data/finanzas/control_gestion.parquet
  - extract_ops_costo_operativo.py        → data/operaciones/costo_operativo.parquet
  - extract_costo_op_proyeccion.py        → data/finanzas/costo_op_proyeccion.parquet

Regla (k-anonimato, K_ANON = 3, evaluado mes a mes):
  - Se borra cuenta_analitica_persona en TODAS las filas (son nombres propios).
  - REMUNERACIONES (sueldos, leyes sociales, bonos, indemnizaciones) se publica solo como total por
    (escenario, kpi, año, mes, línea de negocio, área, sub-área), y solo si el grupo tiene al menos K_ANON
    posiciones ese mes (personas; si el archivo no trae persona, cargos: en la fuente cada persona tiene su
    cargo numerado, ej. OPERARIO-LOGISTICO1, 2, 3).
  - Un grupo que no alcanza se junta con las demás sub-áreas chicas de su área ('OTROS'); si ni así, se suma a
    la sub-área publicable más grande de su misma área (los totales por área no cambian); si el área entera no
    alcanza, va a 'OTRAS ÁREAS'. Si ese residuo tampoco alcanza, absorbe el grupo publicable más chico del mes
    (primero fuera de Operaciones, para no perder el corte Logística / Postventa del costo operativo).
  - Cuenta analítica, canal y tipo de costo se neutralizan en remuneraciones (la comisión variable de un KAM
    es una persona).
  Los totales por escenario, kpi, año, mes y línea de negocio no cambian.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

K_ANON = 3
RESIDUO = ("OTRAS ÁREAS", "OTROS")
_CLAVE = ("escenario", "kpi", "year", "month", "linea_negocio")


def anonimizar_remuneraciones(df: pd.DataFrame, _etiquetas: bool = False) -> pd.DataFrame:
    df = df.copy()
    tiene_persona = "cuenta_analitica_persona" in df.columns
    if tiene_persona:
        persona = df["cuenta_analitica_persona"].fillna("").astype(str).str.strip()
        df["cuenta_analitica_persona"] = ""
    else:
        persona = pd.Series("", index=df.index)
    es = df["centro_costo"].astype(str).str.upper().eq("REMUNERACIONES")
    resto = df[~es]
    rem = df[es & (df["valor"] != 0)].copy()
    if rem.empty:
        return resto.reset_index(drop=True)
    rem["_pos"] = np.where(persona[rem.index] != "", persona[rem.index], rem["cuenta_analitica"].astype(str))
    rem["_ga"], rem["_gs"] = rem["area"], rem["sub_area"]
    clave = [c for c in _CLAVE if c in rem.columns]

    for _, idx in rem.groupby(clave, dropna=False).groups.items():
        g = rem.loc[idx]
        pos = g.groupby(["area", "sub_area"])["_pos"].apply(set).to_dict()

        def grupos(lab):
            out = {}
            for k, l in lab.items():
                out.setdefault(l, set()).update(pos[k])
            return out

        lab = {k: k if len(v) >= K_ANON else (k[0], "OTROS") for k, v in pos.items()}
        G = grupos(lab)
        for k, l in list(lab.items()):
            if l[1] == "OTROS" and len(G[l]) < K_ANON:
                pub = [q for q in G if q[0] == k[0] and q[1] != "OTROS" and len(G[q]) >= K_ANON]
                if pub:
                    lab[k] = max(pub, key=lambda q: len(G[q]))
        G = grupos(lab)
        lab = {k: l if len(G[l]) >= K_ANON else RESIDUO for k, l in lab.items()}
        G = grupos(lab)
        if RESIDUO in G and len(G[RESIDUO]) < K_ANON:
            cands = sorted((l for l in G if l != RESIDUO), key=lambda l: (l[0] == "OPERACIONES", len(G[l])))
            lab = ({k: RESIDUO if l == cands[0] else l for k, l in lab.items()} if cands
                   else {k: ("TOTAL LÍNEA", "TOTAL") for k in lab})
        for (ar, sa), l in lab.items():
            m = rem.index.isin(idx) & (rem["area"] == ar).to_numpy() & (rem["sub_area"] == sa).to_numpy()
            rem.loc[m, "_ga"], rem.loc[m, "_gs"] = l

    rem["area"], rem["sub_area"] = rem["_ga"], rem["_gs"]
    if _etiquetas:
        return rem
    rem["cuenta_analitica"] = "REMUNERACIONES"
    if "canal" in rem.columns:
        rem["canal"] = rem["sub_area"]
    if "tipo_costo" in rem.columns:
        rem["tipo_costo"] = "FIJO"
    keys = [c for c in df.columns if c not in ("valor", "valor_raw")]
    rem = rem.groupby(keys, dropna=False, as_index=False)["valor"].sum()
    out = pd.concat([resto, rem[[c for c in df.columns if c in rem.columns]]], ignore_index=True)
    for c in df.columns:              # concat no debe cambiar los tipos (Int64, fecha, etc.)
        if c in out.columns and out[c].dtype != df[c].dtype:
            try:
                out[c] = out[c].astype(df[c].dtype)
            except (TypeError, ValueError):
                pass
    return out


def verificar(df: pd.DataFrame, nombre: str = "") -> None:
    """Falla si el archivo publicaría detalle personal. Se llama justo antes de grabar."""
    if "cuenta_analitica_persona" in df.columns:
        n = int((df["cuenta_analitica_persona"].fillna("").astype(str).str.strip() != "").sum())
        if n:
            raise RuntimeError(f"{nombre}: {n} filas con nombre de persona; no se publica")
    rem = df[df["centro_costo"].astype(str).str.upper().eq("REMUNERACIONES")]
    otras = set(rem["cuenta_analitica"].astype(str).unique()) - {"REMUNERACIONES"}
    if otras:
        raise RuntimeError(f"{nombre}: remuneraciones con cargo ({sorted(otras)[:3]}); no se publica")
