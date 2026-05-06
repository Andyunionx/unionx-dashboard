' UnionX Contribucion Dashboard - Launcher silencioso
' Lanza el watchdog de PowerShell sin ventana al iniciar sesion

Dim shell
Set shell = CreateObject("WScript.Shell")

shell.Run "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -NonInteractive -File " & _
    Chr(34) & "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\start_contribucion_dashboard.ps1" & Chr(34), _
    0, False

Set shell = Nothing
