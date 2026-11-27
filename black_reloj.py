# -*- coding: utf-8 -*-
"""Reloj del pulso Black 2026: dispara black_pulso.yml a las 08, 12, 16 y 22 h CLT (Andrés, 27-nov).

Mismo esquema que cyber_reloj.py (que no se toca): corre dentro de GitHub Actions (repo público, minutos sin costo) en
reemplazo del cron, que llega con horas de atraso. Un turno dura ~5 h (+40 min de holgura; el job tiene tope 5 h 50): duerme hasta
la próxima hora de pulso, dispara y repite; al acabar el turno se vuelve a disparar a sí mismo. El cron del workflow solo
lo arranca (o lo rearranca si la cadena se corta); el `concurrency` evita dos relojes a la vez.

Ventana: vie 27-nov 12:00 CLT → lun 30-nov 22:00 CLT. Chile en horario de verano: CLT = UTC−3.
Uso: python black_reloj.py [--simular | --prueba]
  --simular: muestra qué haría sin disparar · --prueba: dispara una vez el pulso en modo borrador (solo a Andrés)
"""
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

CLT = timezone(timedelta(hours=-3))
DESDE = datetime(2026, 11, 27, 12, 0, tzinfo=CLT)
HASTA = datetime(2026, 11, 30, 22, 0, tzinfo=CLT)        # último disparo: lun 30 a las 22:00
HORAS = {8, 12, 16, 22}                                   # hora CLT de cada pulso
TURNO = timedelta(hours=5)
HOLGURA = timedelta(minutes=40)     # un pulso que cae hasta 40 min después del turno se espera igual (job: tope 5 h 50)
SIMULAR = '--simular' in sys.argv
PRUEBA = '--prueba' in sys.argv


def gh(*args):
    print('   $ gh', ' '.join(args), flush=True)
    if not SIMULAR:
        subprocess.run(['gh', *args], check=False)


def proximas(desde):
    """Horas de pulso (en punto) estrictamente posteriores a `desde`, dentro de la ventana."""
    t = max(DESDE, (desde + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
    while t <= HASTA:
        if t.astimezone(CLT).hour in HORAS:
            yield t
        t += timedelta(hours=1)


def main():
    if PRUEBA:
        gh('workflow', 'run', 'black_pulso.yml', '-f', 'preborrador=true', '-f', 'forzar_rango=true', '-f', 'force_email=true')
        print('[reloj] prueba: pulso disparado en modo borrador')
        return
    t0 = datetime.now(timezone.utc)
    fin_turno = t0 + TURNO
    if t0 > HASTA:
        print('[reloj] el Black terminó: no hace nada')
        return
    if DESDE - t0 > TURNO + HOLGURA:
        print(f'[reloj] faltan {DESDE - t0} para el Black: sale sin esperar (el cron lo vuelve a arrancar)')
        return
    ultimo = None
    for t in proximas(t0):
        if t > fin_turno + HOLGURA:      # no cabe en este turno: relevo
            break
        espera = (t - datetime.now(timezone.utc)).total_seconds()
        print(f'[reloj] próximo pulso {t.astimezone(CLT):%a %d-%m %H:%M} CLT (en {max(espera, 0) / 60:.0f} min)', flush=True)
        if espera > 0 and not SIMULAR:
            time.sleep(espera)
        gh('workflow', 'run', 'black_pulso.yml')
        ultimo = t
    if next(proximas(ultimo or t0), None) is None:
        print('[reloj] último pulso del Black disparado: fin')
        return
    if ultimo is None:
        # turno sin pulsos (p. ej. de 16:05 a 21:05, o la madrugada): duerme hasta el fin del turno; el próximo pulso queda a más de
        # HOLGURA del relevo, así que el sucesor alcanza a tomarlo
        espera = (fin_turno - datetime.now(timezone.utc)).total_seconds()
        print(f'[reloj] sin pulsos en este turno: espera {espera / 60:.0f} min y releva', flush=True)
        if espera > 0 and not SIMULAR:
            time.sleep(espera)
    # con pulsos: releva justo después del último disparo, así el sucesor parte pasada esa hora y no la repite
    print('[reloj] fin del turno: relevo')
    gh('workflow', 'run', 'black_reloj.yml')


if __name__ == '__main__':
    main()
