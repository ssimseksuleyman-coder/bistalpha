@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title BIST Alpha — Kurulum

echo.
echo ================================================================
echo  BIST ALPHA KURULUM
echo  Konum: %CD%
echo ================================================================
echo.

REM 1) Python kontrolü
echo [1/4] Python kontrol ediliyor...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo HATA: Python yuklu degil.
    echo.
    echo Cozum: https://www.python.org/downloads/ adresinden Python 3.10+
    echo indir ve kurarken "Add Python to PATH" kutusunu MUTLAKA isaretle.
    echo Sonra bu kurulum.bat'i tekrar calistir.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo     OK — Python !PYVER! bulundu
echo.

REM 2) Bagimliliklari kur
echo [2/4] Kutuphaneler kuruluyor (pandas, yfinance, borsapy, ...)
python -m pip install --upgrade pip --quiet 2>nul
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo HATA: Kutuphane kurulumu basarisiz. Internet baglantini kontrol et.
    pause
    exit /b 1
)
echo     OK — tum kutuphaneler kuruldu
echo.

REM 3) Selftest
echo [3/4] Sistem oz-denetimi (11 bolum)...
echo --------------------------------------------------------------
python selftest.py
set TESTRC=%errorlevel%
echo --------------------------------------------------------------
if not %TESTRC%==0 (
    echo.
    echo UYARI: Selftest hata buldu yukarida. Yine de devam edebilirsin
    echo ama once raporu oku.
    echo.
    pause
)
echo.

REM 4) Hizli baslangic ozetini goster
echo [4/4] KURULUM TAMAM
echo.
echo ================================================================
echo  NE YAPABILIRSIN
echo ================================================================
echo.
echo  Backtest karsilastir:
echo     python run_backtest.py --compare
echo.
echo  Bir hisseyi analiz et:
echo     python analyze_stock.py ASELS
echo.
echo  Tek dongu calistir (rapor uretir + Telegram/Email gonderir):
echo     python daemon.py --once kapanis
echo.
echo  Shadow A/B/F durumu:
echo     python shadow.py --status
echo.
echo  Web dashboard'u yerel ac (sonra http://localhost:8000):
echo     dashboard_ac.bat
echo.
echo  7/24 ucretsiz bulutta calistir (bilgisayar kapali):
echo     Bakiniz deploy\UCRETSIZ_7_24_KURULUM.md
echo.
echo  Sistemi her degisiklikte denetle:
echo     python selftest.py
echo.
echo ================================================================
echo.
pause
