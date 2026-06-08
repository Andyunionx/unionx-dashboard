#!/usr/bin/env python3
"""Monitor de salud de workflows críticos. Corre 1 vez al día.

Verifica vía GitHub API el último run exitoso de workflows críticos.
Si alguno lleva > umbral de días sin run exitoso, envía mail de alerta a Andrés.

Variables de entorno:
- GH_TOKEN: token GitHub con read:workflow
- RESEND_API_KEY o GMAIL_TOKEN_JSON (uno de los dos)
- EMAIL_TO (default: andres@unionx.cl)
- EMAIL_FROM (default: onboarding@resend.dev)
"""
import os
import sys
from datetime import datetime, timezone, timedelta
import requests

REPO = 'Andyunionx/unionx-dashboard'
TOKEN = os.environ.get('GH_TOKEN', '')
EMAIL_TO = [e.strip() for e in os.environ.get('EMAIL_TO','andres@unionx.cl').split(',') if e.strip()]
EMAIL_FROM = os.environ.get('EMAIL_FROM','onboarding@resend.dev')

# Workflows críticos y máximo de días sin éxito antes de alertar
WORKFLOWS = {
    'email_diario.yml':   {'nombre':'Pulso Diario', 'max_dias':2, 'frecuencia':'Lun-Vie 08:00 CLT'},
    'cyber_pulso.yml':    {'nombre':'Cyber Pulso',  'max_dias':30, 'frecuencia':'Solo durante Cyber'},
    'sync_mes_actual.yml':{'nombre':'Sync Mes',     'max_dias':1, 'frecuencia':'15min'},
    'sync_diario.yml':    {'nombre':'Sync Ventas',  'max_dias':2, 'frecuencia':'Horario'},
}


def gh_last_success(workflow):
    """Devuelve datetime UTC del último run con conclusion=success, o None."""
    url = f'https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs'
    r = requests.get(url, headers={'Authorization':f'Bearer {TOKEN}'},
                     params={'status':'success','per_page':1}, timeout=30)
    r.raise_for_status()
    runs = r.json().get('workflow_runs', [])
    if not runs:
        return None
    return datetime.fromisoformat(runs[0]['updated_at'].replace('Z','+00:00'))


def send_alert_resend(asunto, html):
    api = os.environ.get('RESEND_API_KEY','')
    if not api:
        print('[WARN] RESEND_API_KEY no seteado, no se envía mail', flush=True)
        return False
    r = requests.post('https://api.resend.com/emails',
        headers={'Authorization':f'Bearer {api}','Content-Type':'application/json'},
        json={'from':EMAIL_FROM,'to':EMAIL_TO,'subject':asunto,'html':html}, timeout=30)
    print(f'[Resend] {r.status_code} {r.text[:200]}', flush=True)
    return r.status_code < 300


def main():
    if not TOKEN:
        print('[ERROR] GH_TOKEN no seteado', flush=True)
        return 1

    ahora = datetime.now(timezone.utc)
    fallas = []
    print(f'=== Monitor workflows {ahora.isoformat()} ===', flush=True)

    for wf, info in WORKFLOWS.items():
        last = gh_last_success(wf)
        if last is None:
            fallas.append({'wf':wf, 'nombre':info['nombre'], 'last':'N/A', 'dias':'∞', 'freq':info['frecuencia']})
            print(f'  [ALERTA] {wf}: SIN runs exitosos registrados', flush=True)
            continue
        dias = (ahora - last).total_seconds() / 86400
        status = 'OK' if dias <= info['max_dias'] else 'ALERTA'
        print(f'  [{status}] {wf}: último éxito hace {dias:.1f} días (umbral {info["max_dias"]}d)', flush=True)
        if dias > info['max_dias']:
            fallas.append({'wf':wf,'nombre':info['nombre'],'last':last.strftime("%Y-%m-%d %H:%M UTC"),
                          'dias':f'{dias:.1f}','freq':info['frecuencia']})

    if not fallas:
        print('\n[OK] Todos los workflows críticos al día.', flush=True)
        return 0

    # Construir alerta HTML
    rows = ''
    for f in fallas:
        rows += f'<tr><td>{f["nombre"]}</td><td>{f["wf"]}</td><td>{f["freq"]}</td><td>{f["last"]}</td><td><b style="color:#DC2626">{f["dias"]} días</b></td></tr>'
    html = f'''<html><body style="font-family:-apple-system,sans-serif;max-width:700px;margin:auto;color:#1E293B">
<h2 style="color:#DC2626">⚠️ Alerta: workflows sin ejecutar a tiempo</h2>
<p>Detectados {len(fallas)} workflows críticos que no han corrido con éxito dentro del umbral.</p>
<table style="width:100%;border-collapse:collapse;font-size:0.9rem">
<thead><tr style="background:#FEE2E2"><th align="left">Workflow</th><th>Archivo</th><th>Frecuencia esperada</th><th>Último éxito</th><th>Días sin éxito</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#64748B;font-size:0.85rem;margin-top:16px">
Acciones sugeridas: 1) Verificar GitHub Actions tab. 2) Disparar manual con gh workflow run. 3) Si está desactivado: gh workflow enable.
</p>
</body></html>'''
    asunto = f'⚠️ {len(fallas)} workflow(s) UnionX sin correr ({ahora.strftime("%d-%b %H:%M UTC")})'
    send_alert_resend(asunto, html)
    return 0


if __name__ == '__main__':
    sys.exit(main())
