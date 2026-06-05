@echo off
chcp 65001 >nul
setlocal
title BIST Alpha - Canli Veri Kontrol
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set DATA_SOURCE=yahoo
echo ================================================================
echo  CANLI VERI KONTROLU - Yahoo/yfinance
echo ================================================================
echo.
python canli_veri_kontrol.py
echo.
pause
