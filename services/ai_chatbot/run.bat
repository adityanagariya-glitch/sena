@echo off
REM Launch the ai_chatbot gateway on Windows. It serves the shell UI and (by
REM default) spawns + health-checks the Staff Streamlit, Policy Streamlit, and
REM Policy API.
REM
REM Activate the venv first, e.g.:  ..\..\sena-ai\Scripts\activate
REM Override settings via env, e.g.:
REM   set GATEWAY_PORT=9100
REM   set MANAGE_CHILDREN=false
REM   run.bat
setlocal
cd /d "%~dp0"

if "%GATEWAY_HOST%"=="" set "GATEWAY_HOST=0.0.0.0"
if "%GATEWAY_PORT%"=="" set "GATEWAY_PORT=9000"

uvicorn gateway:app --host %GATEWAY_HOST% --port %GATEWAY_PORT%

endlocal
