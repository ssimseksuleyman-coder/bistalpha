@echo off
chcp 65001 >nul
title BIST Alpha — Yerel Dashboard

echo.
echo ================================================================
echo  YEREL DASHBOARD ACILIYOR
echo ================================================================
echo.
echo  Adres: http://localhost:8000/
echo  Kapatmak icin: bu pencerede Ctrl+C
echo.
echo  Tarayicida acmazsa yukaridaki adresi elle yapistir.
echo.

REM 5 saniye sonra tarayiciyi ac
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000/"

REM Statik dosya sunucusu (docs/ klasorunden)
python -m http.server -d docs 8000

pause
