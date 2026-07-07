@echo off
setlocal

cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
if not "%BIRDMARK_HOST%"=="" set "HOST=%BIRDMARK_HOST%"
if not "%BIRDMARK_PORT%"=="" set "PORT=%BIRDMARK_PORT%"
set "URL=http://%HOST%:%PORT%"
set "PY=.venv\Scripts\python.exe"

echo [Birdmark] Working directory: %CD%

if not exist "%PY%" (
  echo [Birdmark] Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    python -m venv .venv
  )
  if errorlevel 1 (
    echo [Birdmark] Failed to create .venv.
    pause
    exit /b 1
  )
)

echo [Birdmark] Checking service dependencies...
"%PY%" -c "import fastapi, uvicorn; import multipart" >nul 2>&1
if errorlevel 1 (
  echo [Birdmark] Installing service dependencies...
  "%PY%" -m pip install -r requirements-service.txt
  if errorlevel 1 (
    echo [Birdmark] Failed to install service dependencies.
    pause
    exit /b 1
  )
)

echo [Birdmark] Checking ML runtime dependencies...
"%PY%" -c "import PIL, numpy, ultralytics, bioclip, torch" >nul 2>&1
if errorlevel 1 (
  echo [Birdmark] Missing ML runtime dependencies in .venv.
  echo [Birdmark] Required imports: pillow numpy ultralytics bioclip torch
  echo [Birdmark] Install them in .venv, then run start.bat again.
  pause
  exit /b 1
)

if not exist "models\yolo26m.pt" if not exist "models\yolo26m.engine" (
  echo [Birdmark] Missing model file: models\yolo26m.pt or models\yolo26m.engine
  pause
  exit /b 1
)

if exist "models\yolo26m.engine" (
  "%PY%" -c "import tensorrt" >nul 2>&1
  if errorlevel 1 (
    echo [Birdmark] Found models\yolo26m.engine, but TensorRT is not installed in .venv.
    echo [Birdmark] Run: "%PY%" -m pip install tensorrt
    pause
    exit /b 1
  )
)

if /I "%BIRDMARK_CHECK_ONLY%"=="1" (
  echo [Birdmark] Preflight checks passed.
  exit /b 0
)

"%PY%" -c "import socket; s=socket.socket(); s.settimeout(0.2); raise SystemExit(0 if s.connect_ex(('%HOST%', %PORT%)) == 0 else 1)" >nul 2>&1
if not errorlevel 1 (
  echo [Birdmark] Service already appears to be running.
  start "" "%URL%"
  exit /b 0
)

echo [Birdmark] Browser will open when service is ready at %URL% ...
if /I "%BIRDMARK_NO_BROWSER%"=="1" goto SkipBrowser
start "" powershell -NoProfile -WindowStyle Hidden -Command "$url='%URL%'; $health=$url + '/health'; for ($i=0; $i -lt 300; $i++) { try { $response=Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 1; if ($response.StatusCode -eq 200) { Start-Process $url; exit } } catch { }; Start-Sleep -Seconds 1 }; Start-Process $url"
:SkipBrowser

echo [Birdmark] Starting service. Press Ctrl+C to stop.
"%PY%" -m uvicorn service:app --host %HOST% --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [Birdmark] Service stopped.
pause
exit /b %EXIT_CODE%
