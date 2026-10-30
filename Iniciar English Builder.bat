@echo off
title English Builder
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
echo O servidor foi encerrado. Pressione uma tecla para fechar.
pause >nul
