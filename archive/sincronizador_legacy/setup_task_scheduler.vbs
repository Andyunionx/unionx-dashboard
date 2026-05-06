' Registrar sincronizador en Task Scheduler usando VBS
' Ejecutar con: cscript setup_task_scheduler.vbs

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

TaskName = "UnionX-Sincronizador-Ventas"
ScriptPath = "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA\run_sync.bat"
ProjectPath = "G:\Mi unidad\TRABAJO\RESPALDO\OPERACIONES\UNION X - IA"

WScript.Echo "[1] Creando tarea en Task Scheduler..."

' Comando para crear tarea - cada 5 minutos
CMD = "cmd /c schtasks /create /tn " & TaskName & " /tr """ & ScriptPath & """ /sc minute /mo 5 /f /rl highest /np"

objShell.Run CMD, 0, True

WScript.Echo "[OK] Tarea registrada!"
WScript.Echo "     Nombre: " & TaskName
WScript.Echo "     Frecuencia: Cada 5 minutos"
WScript.Echo "     Script: " & ScriptPath
WScript.Echo ""
WScript.Echo "[2] Iniciando tarea..."

' Iniciar la tarea
CMD2 = "cmd /c schtasks /run /tn " & TaskName
objShell.Run CMD2, 0, True

WScript.Echo "[OK] Tarea iniciada en vivo!"
