@echo off
REM Sync diario ventas_mes_actual.parquet
REM Ejecutado por Windows Task Scheduler todos los dias a las 11:00

cd /d "C:\Users\felip\Desktop\unionx-dashboard"

REM Pull ultimos cambios
git pull origin feat/fc-planif-onboarding --quiet

REM Ejecutar sync (--desde 2026-06-01 para cubrir el historico congelado incompleto)
python sync_ventas_mes_actual.py --desde 2026-06-01 >> "data\logs\sync_ventas.log" 2>&1

REM Commit y push si hubo cambios
git add data\historico\ventas_mes_actual.parquet
git diff --staged --quiet && (echo Sin cambios hoy >> data\logs\sync_ventas.log) || (
    git commit -m "data: sync ventas_mes_actual diario auto"
    git push origin feat/fc-planif-onboarding
)
