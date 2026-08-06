@echo off
setlocal
where py.exe >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0sync_model_catalog.py" %*
exit /b %errorlevel%

:use_python
python "%~dp0sync_model_catalog.py" %*
exit /b %errorlevel%
