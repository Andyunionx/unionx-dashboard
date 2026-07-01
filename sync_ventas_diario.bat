@echo off
REM Sync diario ventas_mes_actual.parquet
REM Ejecutado por Windows Task Scheduler todos los dias a las 11:00

cd /d "C:\Users\felip\Desktop\unionx-dashboard"

REM Pull ultimos cambios (main es la rama del app en produccion)
git pull origin main --quiet

REM Ejecutar sync (lee CUTOFF_HISTORICO desde views/shared.py automaticamente)
python sync_ventas_mes_actual.py >> "data\logs\sync_ventas.log" 2>&1

REM Commit y push si hubo cambios
git add data\historico\ventas_mes_actual.parquet
git diff --staged --quiet && (echo Sin cambios hoy >> data\logs\sync_ventas.log) || (
    git commit -m "data: sync ventas_mes_actual diario auto"
    git push origin feat/fc-planif-onboarding
    git push origin main
)
