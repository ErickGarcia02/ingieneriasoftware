@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps
where py >nul 2>&1
if errorlevel 1 goto pythoncmd
py -3 -m venv .venv
if errorlevel 1 goto fallo
goto deps
:pythoncmd
python -m venv .venv
if errorlevel 1 goto fallo
:deps
fc /b "requirements.txt" ".venv\cast-requirements.txt" >nul 2>&1
if not errorlevel 1 goto run
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fallo
copy /y "requirements.txt" ".venv\cast-requirements.txt" >nul
:run
".venv\Scripts\python.exe" -m streamlit run app.py --server.address localhost
if not errorlevel 1 exit /b 0
:fallo
echo Revisa el mensaje anterior. Se requiere Python 3.11 a 3.14 e Internet en el primer inicio.
pause
