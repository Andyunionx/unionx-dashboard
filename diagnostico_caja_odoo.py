# -*- coding: utf-8 -*-
"""
FASE B del diagnostico de caja — ¿A QUIEN se le pago? (Odoo, SOLO LECTURA)

Extrae los movimientos de todos los diarios de banco/caja de Comercial Innovatek
(company_id=1) desde dic-2025, arma la matriz de contrapartidas por asiento
(patron de analisis_210215_forense.py) y clasifica las salidas en buckets por
cuenta contable + partner + glosa.

Salidas: data/outputs/diagnostico_caja_odoo_2026.xlsx + parquet + resumen consola.
NUNCA escribe en Odoo (solo search_read).
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "finanzas-unionx" / "backend"))
from app.core.odoo_client import OdooClient  # noqa: E402

DESDE = "2025-12-01"
COMPANY_ID = 1  # Comercial Innovatek SpA (Dinasty Partners=2 queda fuera)
OUT_DIR = ROOT / "data" / "outputs"


def conectar() -> OdooClient:
    pw = (os.environ.get("OPS_ODOO_PASSWORD", "").strip()
          or os.environ.get("ANDRES_ODOO_PASSWORD", "").strip())
    if not pw:
        p = ROOT / "odoo" / ".odoo_pass"
        if p.exists():
            pw = p.read_text().strip()
    if not pw:
        raise SystemExit("Sin password Odoo (ANDRES_ODOO_PASSWORD).")
    cli = OdooClient(
        url=os.environ.get("ODOO_URL", "https://unionxb2b.odoo.com"),
        db=os.environ.get("ODOO_DB", "bmya-innovatek-sh-prd-6981800"),
        username=(os.environ.get("OPS_ODOO_USER", "").strip()
                  or os.environ.get("ANDRES_ODOO_USER", "").strip()
                  or "andres@grupoeter.cl"),
        password=pw,
        max_retries=3,
    )
    cli.authenticate()
    return cli


# ---------- clasificacion ----------
BUCKETS = [
    # (bucket, test) — se evalua en orden; primera que calza gana
    ("Traspaso entre cuentas propias",
     lambda c, n, p, g: c.startswith("1101") or c.startswith("1105") or c == "100101" and False),
    ("Transitoria sin aplicar (100101)", lambda c, n, p, g: c == "100101"),
    ("Remuneraciones",
     lambda c, n, p, g: c.startswith("210202") or c.startswith("4342") or c.startswith("110304")
     or "remuner" in n or "sueldo" in n or "nomina" in g or "nómina" in g or "buk" in g),
    ("Imposiciones / previsión",
     lambda c, n, p, g: "previred" in (n + g + p) or "imposicion" in n or "afp" in n or "isapre" in n
     or c.startswith("210203") or c.startswith("210204")),
    ("Cobros de clientes (facturas)", lambda c, n, p, g: c in ("110401",)),
    ("Financiamiento: factoring", lambda c, n, p, g: c in ("110402",) or "factoring" in n),
    ("Importación: aduana/internación",
     lambda c, n, p, g: c == "110312" or "aduana" in n or "aduana" in p or "pedro serrano" in (n + p)),
    ("SII / impuestos",
     lambda c, n, p, g: "impuesto" in n or "iva " in (n + " ") or n.startswith("iva") or "sii" in g
     or "tesoreria" in p or "tesorería" in p or c.startswith("2104")),
    ("Proveedores importación",
     lambda c, n, p, g: c.startswith("210215") or c.startswith("1110")
     or "topwill" in p or "ohnso" in p or "import" in n),
    ("Deuda: amortización bancos",
     lambda c, n, p, g: (c.startswith("21") and ("banco" in n or "prestamo" in n or "préstamo" in n
                                                 or "obligacion" in n or "obligación" in n or "leasing" in n))
     or "credito" in n or "crédito" in n),
    ("Deuda: intereses y gastos financieros",
     lambda c, n, p, g: "interes" in n or "interés" in n or "gasto bancario" in n or "comision bancaria" in n
     or "comisión bancaria" in n or c.startswith("47") or c == "120101"),
    ("Socios / relacionadas",
     lambda c, n, p, g: "socio" in n or "empresa relacionada" in n or "cta cte" in n or "cuenta corriente" in n),
    ("Comisiones marketplaces",
     lambda c, n, p, g: "mercado libre" in p or "mercadolibre" in p or "falabella" in p or "ripley" in p
     or "walmart" in p or "paris" in p or "comision" in n or "comisión" in n),
    ("Proveedores nacionales / CxP",
     lambda c, n, p, g: c.startswith("2101") or c.startswith("2102")),
    ("Clientes (cobros)", lambda c, n, p, g: c.startswith("1102") or c.startswith("1103") or "clientes" in n),
]


def clasificar(codigo, cuenta_nombre, partner, glosa):
    c = str(codigo or "")
    n = str(cuenta_nombre or "").lower()
    p = str(partner or "").lower()
    g = str(glosa or "").lower()
    # traspasos: contrapartida es otra cuenta de banco (asset_cash) — se marca antes con flag aparte
    for bucket, test in BUCKETS[1:]:
        try:
            if test(c, n, p, g):
                return bucket
        except Exception:
            pass
    return f"Otros ({c[:4]} {cuenta_nombre})"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cli = conectar()
    print(f"Conectado. Extraccion fechada: {datetime.now().isoformat()} (libros abiertos desde abril)")

    # 1) diarios banco/caja de Innovatek
    journals = cli.search_read_paginated(
        "account.journal",
        [("type", "in", ["bank", "cash"]), ("company_id", "=", COMPANY_ID)],
        ["id", "name", "code", "type", "default_account_id"])
    j_ids = [j["id"] for j in journals]
    print(f"Diarios banco/caja Innovatek: {len(j_ids)}")

    # cuentas asset_cash (para detectar traspasos banco->banco)
    cash_accs = cli.search_read_paginated(
        "account.account", [("account_type", "=", "asset_cash")], ["id", "code", "name"])
    cash_ids = {a["id"] for a in cash_accs}

    # 2) lineas de banco (posted, desde DESDE)
    print("Leyendo lineas de banco...")
    bank_lines = cli.search_read_paginated(
        "account.move.line",
        [("journal_id", "in", j_ids), ("parent_state", "=", "posted"), ("date", ">=", DESDE),
         ("account_id", "in", list(cash_ids))],
        ["id", "move_id", "date", "journal_id", "account_id", "debit", "credit", "balance"],
        page_size=1000)
    print(f"  {len(bank_lines):,} lineas de banco")
    move_ids = sorted({l["move_id"][0] for l in bank_lines if l.get("move_id")})
    print(f"  {len(move_ids):,} asientos")

    # 3) TODAS las lineas de esos asientos (contrapartidas incluidas)
    print("Leyendo contrapartidas por lotes...")
    all_lines = []
    B = 2000
    for i in range(0, len(move_ids), B):
        batch = move_ids[i:i + B]
        all_lines += cli.search_read_paginated(
            "account.move.line",
            [("move_id", "in", batch), ("parent_state", "=", "posted")],
            ["id", "move_id", "date", "journal_id", "account_id", "partner_id", "name",
             "debit", "credit", "balance"],
            page_size=1000)
        print(f"  lote {i//B + 1}/{(len(move_ids)-1)//B + 1}: {len(all_lines):,} lineas acumuladas")

    df = pd.DataFrame([{
        "move_id": l["move_id"][0] if l.get("move_id") else None,
        "move_name": l["move_id"][1] if l.get("move_id") else "",
        "date": l["date"],
        "journal": l["journal_id"][1] if l.get("journal_id") else "",
        "account_id": l["account_id"][0] if l.get("account_id") else None,
        "account": l["account_id"][1] if l.get("account_id") else "",
        "partner": l["partner_id"][1] if l.get("partner_id") else "",
        "glosa": l.get("name") or "",
        "balance": l.get("balance") or 0.0,
    } for l in all_lines])
    df["date"] = pd.to_datetime(df["date"])
    df["mes"] = df["date"].dt.to_period("M").astype(str)
    df["codigo"] = df["account"].str.extract(r"^(\d+)")
    df["es_banco"] = df["account_id"].isin(cash_ids)

    # 4) contrapartidas: el destino/origen de la plata es el balance de la linea NO-banco
    contra = df[~df["es_banco"]].copy()
    # traspasos banco->banco: asientos donde TODAS las lineas son cuentas cash
    solo_banco = df.groupby("move_id")["es_banco"].all()
    traspaso_moves = set(solo_banco[solo_banco].index)
    contra_t = df[df["move_id"].isin(traspaso_moves) & (df["balance"] > 0)].copy()
    contra_t["bucket"] = "Traspaso entre cuentas propias"

    contra["bucket"] = [
        clasificar(c, a, p, g) for c, a, p, g in
        zip(contra["codigo"], contra["account"], contra["partner"], contra["glosa"])]
    full = pd.concat([contra, contra_t], ignore_index=True)

    # 5) resumen: bucket x mes (balance>0 = plata que SALIO del banco hacia ahi)
    full.to_parquet(OUT_DIR / "diagnostico_caja_odoo_lineas.parquet", index=False)
    piv = (full.pivot_table(index="bucket", columns="mes", values="balance", aggfunc="sum") / 1e6).round(1)
    piv["TOTAL"] = piv.sum(axis=1)
    piv = piv.sort_values("TOTAL", ascending=False)

    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.max_rows", 100)
    print("\n=== FLUJO POR BUCKET x MES (MM CLP; + = salida neta de caja hacia ese destino) ===")
    print(piv.to_string())

    print("\n=== TOP 25 CONTRAPARTES (partner) POR SALIDA NETA (MM) ===")
    top = (full[full["balance"] > 0].groupby(["bucket", "partner"])["balance"].sum()
           .sort_values(ascending=False).head(25) / 1e6).round(1)
    print(top.to_string())

    print("\n=== TRANSITORIA 100101 — detalle (MM) ===")
    tr = full[full["codigo"] == "100101"]
    if len(tr):
        print((tr.groupby(["mes", "glosa"])["balance"].sum().sort_values(ascending=False).head(20) / 1e6)
              .round(1).to_string())

    # Excel
    with pd.ExcelWriter(OUT_DIR / "diagnostico_caja_odoo_2026.xlsx", engine="openpyxl") as xw:
        piv.to_excel(xw, sheet_name="Bucket x Mes (MM)")
        (full[full["balance"] > 0].groupby(["bucket", "partner"])["balance"].sum()
         .sort_values(ascending=False).head(200) / 1e6).round(2).to_excel(xw, sheet_name="Top contrapartes")
        (full.groupby(["bucket", "codigo", "account"])["balance"].sum()
         .sort_values(ascending=False) / 1e6).round(2).to_excel(xw, sheet_name="Por cuenta")
        if len(tr):
            (tr[["date", "move_name", "journal", "partner", "glosa", "balance"]]
             .sort_values("date")).to_excel(xw, sheet_name="Transitoria 100101", index=False)
    print(f"\nOK -> {OUT_DIR / 'diagnostico_caja_odoo_2026.xlsx'}")


if __name__ == "__main__":
    main()
