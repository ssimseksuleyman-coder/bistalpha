@echo off
chcp 65001 >nul
setlocal
title BIST Alpha - Canli Dongu
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set DATA_SOURCE=yahoo
echo ================================================================
echo  BIST ALPHA CANLI DONGU - Yahoo/yfinance
echo ================================================================
echo.
python daemon.py --once canli
set RC=%errorlevel%
echo.
if not "%RC%"=="0" (
  echo HATA: Canli dongu basarisiz oldu. Yukaridaki mesaji kontrol et.
) else (
  echo OK: Canli dongu tamamlandi. Dashboard state guncellendi.
)
echo.
pause
