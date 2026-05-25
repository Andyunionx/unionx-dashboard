#!/usr/bin/env python3
"""
Sync Maestra Canales desde Drive (Maestra B2B) → Maestra Canales.xlsx + canal_tipo_negocio.json

Estrategia: Drive prioridad, local fallback (case-insensitive).

Para cada canal:
- Si aparece en Drive (pestaña CanalxKam): usa TN/KAM/Estado del Drive
- Si NO aparece pero está en JSON local: conserva el local
- Mantiene variantes de capitalización para compat con extracts antiguos (Linux vs Drive)

Para cada empresa (partner):
- Si aparece en Drive (pestaña Empresa): usa canal del Drive
- Si NO aparece pero está en Maestra Canales.xlsx local: conserva el local

Output:
- data/planillas/Maestra Canales.xlsx (Empresa → Canal)
- data/planillas/canal_tipo_negocio.json (Canal → {tipo_negocio, kam, estado_canal})
- data/planillas/Maestra B2B Drive.xlsx (snapshot raw del Drive)

Uso:
    python sync_maestra_canales_drive.py
"""
import base64
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
PLANILLAS = PROJECT_ROOT / 'data' / 'planillas'
DRIVE_FILE_ID = '1QqIaF__kAMnE6bmrp6PfYC9p2HES9I8Y'

LOCAL_EMPRESA = PLANILLAS / 'Maestra Canales.xlsx'
LOCAL_JSON = PLANILLAS / 'canal_tipo_negocio.json'
DRIVE_SNAPSHOT = PLANILLAS / 'Maestra B2B Drive.xlsx'


def _load_env():
    env = PROJECT_ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def download_drive_xlsx():
    """Baja el xlsx desde Drive vía service account.

    Requiere: gcp_service_account credentials. Si no, usa el snapshot local.
    """
    print(f"[1] Descargando Drive file {DRIVE_FILE_ID}...")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        import io

        # Cargar credenciales del service account (mismo patrón que agente-cobranza)
        SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON', '').strip()
        if creds_json:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            sa_path = PROJECT_ROOT / 'credentials.json'
            if not sa_path.exists():
                raise FileNotFoundError(f"No GOOGLE_CREDENTIALS_JSON env ni {sa_path}")
            creds = service_account.Credentials.from_service_account_file(
                str(sa_path), scopes=SCOPES
            )

        service = build('drive', 'v3', credentials=creds)
        req = service.files().get_media(fileId=DRIVE_FILE_ID)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        DRIVE_SNAPSHOT.write_bytes(buf.getvalue())
        size_kb = DRIVE_SNAPSHOT.stat().st_size / 1024
        print(f"   [OK] {DRIVE_SNAPSHOT.name} ({size_kb:.0f} KB)")
        return True
    except Exception as e:
        print(f"   [WARN] No se pudo bajar desde Drive ({type(e).__name__}: {e})")
        if DRIVE_SNAPSHOT.exists():
            mod = datetime.fromtimestamp(DRIVE_SNAPSHOT.stat().st_mtime).isoformat()
            print(f"   Usando snapshot existente: {DRIVE_SNAPSHOT.name} (modificado {mod})")
            return True
        print(f"   [ERROR] Sin snapshot local, abortando.")
        return False


def main():
    _load_env()

    if not download_drive_xlsx():
        sys.exit(1)

    # ============================
    # Cargar Drive
    # ============================
    print(f"\n[2] Cargando pestañas Drive...")
    emp_drive = pd.read_excel(DRIVE_SNAPSHOT, sheet_name='Empresa')
    emp_drive = emp_drive.dropna(subset=['Empresa', 'Canal']).copy()
    emp_drive['Empresa'] = emp_drive['Empresa'].astype(str).str.strip()
    emp_drive['Canal'] = emp_drive['Canal'].astype(str).str.strip()
    print(f"   Empresa Drive: {len(emp_drive)} filas")

    ckm_drive = pd.read_excel(DRIVE_SNAPSHOT, sheet_name='CanalxKam')
    ckm_drive = ckm_drive.dropna(subset=['Canal']).copy()
    ckm_drive['Canal'] = ckm_drive['Canal'].astype(str).str.strip()
    print(f"   CanalxKam Drive: {len(ckm_drive)} filas")

    # ============================
    # Cargar local (fallback)
    # ============================
    print(f"\n[3] Cargando locales (fallback)...")
    emp_local = pd.read_excel(LOCAL_EMPRESA, sheet_name='Sheet1') if LOCAL_EMPRESA.exists() else pd.DataFrame(columns=['Empresa', 'Canal'])
    if not emp_local.empty:
        emp_local['Empresa'] = emp_local['Empresa'].astype(str).str.strip()
        emp_local['Canal'] = emp_local['Canal'].astype(str).str.strip()
    print(f"   Empresa local: {len(emp_local)} filas")

    ckm_local = json.loads(LOCAL_JSON.read_text(encoding='utf-8')) if LOCAL_JSON.exists() else {}
    print(f"   CanalxKam local (JSON): {len(ckm_local)} entries")

    # ============================
    # MERGE Empresa
    # ============================
    print(f"\n[4] Merge Empresa: Drive prioridad, local fallback (case-insensitive)...")
    empresas_drive_lower = set(emp_drive['Empresa'].str.lower())
    rows_extra_local = emp_local[~emp_local['Empresa'].str.lower().isin(empresas_drive_lower)]
    print(f"   Empresas exclusivas en local (conservadas): {len(rows_extra_local)}")
    for _, r in rows_extra_local.iterrows():
        print(f"     [LOCAL-ONLY] {r['Empresa']} -> {r['Canal']}")

    emp_final = pd.concat([emp_drive, rows_extra_local], ignore_index=True)
    emp_final = emp_final.drop_duplicates(subset=['Empresa'], keep='first')
    print(f"   Empresa final: {len(emp_final)} filas")

    # ============================
    # MERGE CanalxKam
    # ============================
    print(f"\n[5] Merge CanalxKam: Drive prioridad, local fallback (con variantes case)...")
    ckm_final = {}

    # 1) Drive entries (limpios)
    for _, r in ckm_drive.iterrows():
        canal = r['Canal']
        tn = str(r.get('Tipo Negocio', '') or '').strip()
        kam = str(r.get('KAM', '') or '').strip() if pd.notna(r.get('KAM')) else ''
        estado = str(r.get('Estado Canal', '') or '').strip() if pd.notna(r.get('Estado Canal')) else ''
        if not canal or not tn:
            continue
        entry = {'tipo_negocio': tn, 'kam': kam}
        if estado:
            entry['estado_canal'] = estado
        ckm_final[canal] = entry

    # 2) Variantes case (para compat con extracts viejos: "Lhotse Web" Drive, "Lhotse web" Odoo)
    canales_drive_lower = {k.lower(): k for k in ckm_final.keys()}
    n_variantes = 0
    for canal_local, info in ckm_local.items():
        if canal_local.lower() in canales_drive_lower:
            # Si Drive tiene el canal con otro case, copiar entry Drive bajo el nombre local también
            canal_drive_key = canales_drive_lower[canal_local.lower()]
            if canal_local not in ckm_final:
                ckm_final[canal_local] = ckm_final[canal_drive_key]
                n_variantes += 1
        else:
            # Canal solo en local: conservar
            ckm_final[canal_local] = info
            print(f"     [LOCAL-ONLY] {canal_local} -> {info}")

    print(f"   Variantes case agregadas: {n_variantes}")
    print(f"   CanalxKam final: {len(ckm_final)} entries")

    # ============================
    # Backup + Guardar
    # ============================
    print(f"\n[6] Backup + guardar...")
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if LOCAL_EMPRESA.exists():
        bk = LOCAL_EMPRESA.with_suffix(f'.backup_{ts}.xlsx')
        shutil.copy(LOCAL_EMPRESA, bk)
        print(f"   Backup {bk.name}")
    if LOCAL_JSON.exists():
        bkj = LOCAL_JSON.with_suffix(f'.backup_{ts}.json')
        shutil.copy(LOCAL_JSON, bkj)

    with pd.ExcelWriter(LOCAL_EMPRESA, engine='openpyxl') as w:
        emp_final.to_excel(w, sheet_name='Sheet1', index=False)
    print(f"   [OK] {LOCAL_EMPRESA.name} ({len(emp_final)} filas)")

    LOCAL_JSON.write_text(json.dumps(ckm_final, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"   [OK] {LOCAL_JSON.name} ({len(ckm_final)} entries)")

    print(f"\n[DONE] Sync completado.")


if __name__ == '__main__':
    main()
