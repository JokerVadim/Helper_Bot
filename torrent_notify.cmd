@echo off
chcp 65001 >nul
echo %~1 > "%TEMP%\torrent_name.txt"
if not "%~2" == "" (
    echo %~2 > "%TEMP%\torrent_files.txt"
) else (
    type nul > "%TEMP%\torrent_files.txt"
)
start /B "" pythonw "%~dp0torrent_notify.py"