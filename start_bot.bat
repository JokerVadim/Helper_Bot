@echo off
cd /d "%~dp0"

:: Найти и остановить запущенный бот
echo Stopping bot...
for /f "tokens=1,* delims= " %%a in ('wmic process where "commandline like '%%bot.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo Stopping process %%a...
    taskkill /F /PID %%a >nul 2>&1
)
echo Bot stopped.

:: Запустить бота
echo Starting bot...
start "" envs\Scripts\python.exe bot.py

:: Закрыть окно консоли
timeout /t 2 >nul
exit

