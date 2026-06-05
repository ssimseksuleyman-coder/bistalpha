@echo off
chcp 65001 >nul
setlocal
title BIST Alpha - 7/24 GitHub Kontrol
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python github_724_kontrol.py
echo.
pause
