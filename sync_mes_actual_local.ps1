# Sync mes actual local (bypass Turso).
# Extract Odoo -> parquet -> commit + push para que Streamlit Cloud lo levante.
# Disenado para correr en Windows Task Scheduler cada 4h.
#
# Uso manual: powershell -ExecutionPolicy Bypass -File sync_mes_actual_local.ps1

$ErrorActionPreference = "Continue"
$ProjectPath = "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"
$PythonExe = "C:\Users\andre\AppData\Local\Programs\Python\Python312\python.exe"
$LogDir = "$ProjectPath\data\db"
$LogFile = "$LogDir\sync_mes_actual_local.log"

# Setup log
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
function Log($msg) {
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$ts $msg" | Tee-Object -FilePath $LogFile -Append
}

Log "=== START sync_mes_actual_local ==="
Set-Location $ProjectPath
$env:PYTHONIOENCODING = "utf-8"

# 0) Sync Maestra Canales desde Drive (Drive prioridad + local fallback)
Log "[0] Sync Maestra Canales desde Drive (Maestra B2B)..."
& $PythonExe "sync_maestra_canales_drive.py" 2>&1 | Tee-Object -FilePath $LogFile -Append
Log "[0] Exit code sync canales: $LASTEXITCODE (no bloquea si falla)"

# 1) Extract Odoo -> parquet
Log "[1] Ejecutando extract_mes_actual_a_parquet.py --source odoo..."
& $PythonExe "extract_mes_actual_a_parquet.py" "--source" "odoo" 2>&1 | Tee-Object -FilePath $LogFile -Append
$exitCode = $LASTEXITCODE
Log "[1] Exit code: $exitCode"

if ($exitCode -ne 0) {
    Log "[ERROR] Extract fallo. Abortando push."
    exit $exitCode
}

# 2) Git ops
Log "[2] git pull --rebase para evitar conflictos..."
git pull --rebase origin main 2>&1 | Tee-Object -FilePath $LogFile -Append

Log "[3] git add parquet + maestra canales sincronizadas..."
git add "data/historico/ventas_mes_actual.parquet" 2>&1 | Tee-Object -FilePath $LogFile -Append
git add "data/planillas/Maestra Canales.xlsx" "data/planillas/canal_tipo_negocio.json" "data/planillas/Maestra B2B Drive.xlsx" 2>&1 | Tee-Object -FilePath $LogFile -Append

# Solo commit si hay cambios
$diff = git diff --staged --quiet
if ($LASTEXITCODE -eq 0) {
    Log "[3] Sin cambios en parquet, nada que commitear"
} else {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm")
    git commit -m "Sync mes actual local: $ts UTC" 2>&1 | Tee-Object -FilePath $LogFile -Append
    Log "[4] git push..."
    git push origin main 2>&1 | Tee-Object -FilePath $LogFile -Append
    Log "[4] Exit code push: $LASTEXITCODE"
}

Log "=== END sync_mes_actual_local ==="
