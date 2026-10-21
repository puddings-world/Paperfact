' Launch the reader with no console window.
'
' Needed because uv's venv ships pythonw.exe as a trampoline that re-execs the
' CONSOLE python.exe, so launching through it leaves a terminal sitting behind the
' reader. Copying the real pythonw.exe into the venv does not work either: it cannot
' find python311.dll, which uv does not place beside it, and fails silently.
'
' WScript.Shell.Run with intWindowStyle 0 starts the process with its window hidden,
' which is the one approach that does not depend on how the launcher was built.
'
' Optional argument: --next, to open straight onto the next unread paper.

Option Explicit

Dim fso, shell, scriptDir, repo, python, args, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repo = fso.GetParentFolderName(scriptDir)
python = fso.BuildPath(repo, ".venv\Scripts\python.exe")

If Not fso.FileExists(python) Then
    MsgBox "Paperfact is not set up yet." & vbCrLf & vbCrLf & _
           "Run scripts\setup.ps1 first." & vbCrLf & vbCrLf & _
           "(looked for " & python & ")", vbExclamation, "Paperfact"
    WScript.Quit 1
End If

args = ""
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "--next" Then args = " --next"
End If

shell.CurrentDirectory = repo
command = """" & python & """ -m paper_daily app" & args
shell.Run command, 0, False
