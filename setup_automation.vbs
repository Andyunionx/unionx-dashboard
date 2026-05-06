' Script VBS para ejecutar PowerShell como Administrador
' Autoriza permisos y configura Task Scheduler automáticamente

Set objShell = CreateObject("Shell.Application")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Directorio del proyecto
strProjectDir = "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"

' Script PowerShell a ejecutar
strPS_Script = "C:\Windows\Temp\setup_scheduler.ps1"

' Crear script PowerShell en temp
Set objFile = objFSO.CreateTextFile(strPS_Script, True)
objFile.WriteLine("$ScriptDir = """ & strProjectDir & """")
objFile.WriteLine("$TaskName = ""UnionX-Sincronizador-Ventas""")
objFile.WriteLine("$ScriptPath = ""$ScriptDir\run_sync.bat""")
objFile.WriteLine("")
objFile.WriteLine("Write-Host ""[SETUP] Registrando sincronizador en Task Scheduler..."" -ForegroundColor Green")
objFile.WriteLine("")
objFile.WriteLine("# Eliminar si existe")
objFile.WriteLine("if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {")
objFile.WriteLine("    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false")
objFile.WriteLine("    Write-Host ""[1/3] Tarea anterior eliminada...""")
objFile.WriteLine("}")
objFile.WriteLine("")
objFile.WriteLine("# Trigger cada 5 minutos")
objFile.WriteLine("$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)")
objFile.WriteLine("Write-Host ""[2/3] Trigger creado (cada 5 minutos)...""")
objFile.WriteLine("")
objFile.WriteLine("# Acción")
objFile.WriteLine("$action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $ScriptDir")
objFile.WriteLine("")
objFile.WriteLine("# Principal y Settings")
objFile.WriteLine("$Principal = New-ScheduledTaskPrincipal -UserId ""$env:USERDOMAIN\$env:USERNAME"" -RunLevel Highest")
objFile.WriteLine("$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries:$false -StartWhenAvailable:$true -MultipleInstances ""IgnoreNew""")
objFile.WriteLine("")
objFile.WriteLine("# Registrar tarea")
objFile.WriteLine("Register-ScheduledTask -TaskName $TaskName -Description ""Sincroniza ventas de Odoo cada 5 minutos"" -Trigger $trigger -Action $action -Principal $Principal -Settings $Settings -Force | Out-Null")
objFile.WriteLine("")
objFile.WriteLine("Write-Host ""[3/3] Registrado en Task Scheduler""")
objFile.WriteLine("Write-Host """"")
objFile.WriteLine("Write-Host ""[OK] SINCRONIZADOR ACTIVADO"" -ForegroundColor Green")
objFile.WriteLine("Write-Host ""     Intervalo: Cada 5 minutos""")
objFile.WriteLine("Write-Host ""     Logs: $ScriptDir\logs\sincronizador.log""")
objFile.WriteLine("Write-Host """"")
objFile.WriteLine("Write-Host ""Presiona cualquier tecla para salir...""")
objFile.WriteLine("$null = $Host.UI.RawUI.ReadKey(""NoEcho,IncludeKeyDown"")")
objFile.Close()

' Ejecutar PowerShell como Admin
objShell.ShellExecute "powershell.exe", "-ExecutionPolicy Bypass -NoProfile -File """ & strPS_Script & """", "", "runas", 1

' Limpiar después de 10 segundos
WScript.Sleep 10000
On Error Resume Next
objFSO.DeleteFile strPS_Script
On Error Goto 0
