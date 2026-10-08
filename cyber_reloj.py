# -*- coding: utf-8 -*-
"""Reloj del pulso Cyber: dispara cyber_pulso.yml cada hora en punto durante el Cyber.

Corre dentro de GitHub Actions (repo público: minutos gratis) en reemplazo del cron, que
llega con horas de atraso. Una corrida dura hasta ~5 h 30 (el tope de un job es 6 h):
duerme hasta la próxima hora en punto, dispara el pulso y repite; al acabar su turno
se vuelve a disparar a sí mismo para seguir. El cron del workflow solo lo arranca (o lo
rearranca si la cadena se corta); el `concurrency` evita que haya dos relojes a la vez.

Ventana: lun 5-oct 06:00 CLT → lun 12-oct 06:00 CLT (UTC−3). Fuera de ella no hace nada.
A las 08, 14 y 18 h CLT también dispara cyber_planilla.yml (planilla de operaciones en Drive), que
espera 10 min para no cruzar su extracción de Odoo con la del pulso. No se encadena con workflow_run
porque GitHub no dispara workflows a partir de corridas lanzadas con el GITHUB_TOKEN.
Uso: python cyber_reloj.py [--simular | --prueba]   (--simular: muestra qué haría; --prueba: dispara una vez el pulso en borrador)
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

DESDE = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
HASTA = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
TURNO = timedelta(hours=5, minutes=30)
HORAS_PLANILLA = {8, 14, 18}     # hora CLT en que se actualiza la planilla de operaciones
SIMULAR = '--simular' in sys.argv
PRUEBA = '--prueba' in sys.argv     # dispara una vez el pulso en modo borrador (verifica permisos)


def gh(*args):
    print('   $ gh', ' '.join(args), flush=True)
    if not SIMULAR:
        subprocess.run(['gh', *args], check=False)


def main():
    if PRUEBA:
        gh('workflow', 'run', 'cyber_pulso.yml', '-f', 'preborrador=true', '-f', 'forzar_rango=true')
        print('[reloj] prueba: pulso disparado en modo borrador')
        return
    t0 = datetime.now(timezone.utc)
    fin_turno = t0 + TURNO
    if t0 >= HASTA:
        print('[reloj] el Cyber terminó: no hace nada')
        return
    if DESDE - t0 > TURNO:
        print(f'[reloj] faltan {DESDE - t0} para el Cyber: sale sin esperar (el cron lo vuelve a arrancar)')
        return
    proxima = max(DESDE, (t0 + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
    # siempre la hora siguiente: el relevo arranca segundos después del último disparo y no debe repetirlo
    while proxima < HASTA and proxima <= fin_turno:
        espera = (proxima - datetime.now(timezone.utc)).total_seconds()
        print(f'[reloj] próximo disparo {proxima:%Y-%m-%d %H:%M} UTC (en {max(espera, 0) / 60:.0f} min)', flush=True)
        if espera > 0 and not SIMULAR:
            time.sleep(espera)
        gh('workflow', 'run', 'cyber_pulso.yml')
        if (proxima - timedelta(hours=3)).hour in HORAS_PLANILLA:
            gh('workflow', 'run', 'cyber_planilla.yml', '-f', 'esperar_min=10')
        proxima += timedelta(hours=1)
    if proxima < HASTA:
        print('[reloj] fin del turno: relevo')
        gh('workflow', 'run', 'cyber_reloj.yml')
    else:
        print('[reloj] última hora del Cyber disparada: fin')


if __name__ == '__main__':
    main()
