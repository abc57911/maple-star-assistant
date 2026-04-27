Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
venvPythonw = scriptDir & "\.venv-paddleocr\Scripts\pythonw.exe"
If fso.FileExists(venvPythonw) Then
    pythonw = venvPythonw
Else
    pythonw = "pythonw"
End If
shell.CurrentDirectory = scriptDir
shell.Run """" & pythonw & """ """ & scriptDir & "\main.pyw""", 0, False
