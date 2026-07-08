@echo off
setlocal

cd /d "%~dp0"

if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not defined %%A set "%%A=%%B"
  )
)

set "HOST=127.0.0.1"
set "PORT=8100"
if not "%BIRDMARK_API_HOST%"=="" set "HOST=%BIRDMARK_API_HOST%"
if not "%BIRDMARK_API_PORT%"=="" set "PORT=%BIRDMARK_API_PORT%"
set "URL=http://%HOST%:%PORT%"
set "PY=.venv\Scripts\python.exe"

if "%PYTHONPATH%"=="" (
  set "PYTHONPATH=%CD%"
) else (
  set "PYTHONPATH=%CD%;%PYTHONPATH%"
)

echo [Birdmark API] Working directory: %CD%

if not exist "%PY%" (
  echo [Birdmark API] Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    python -m venv .venv
  )
  if errorlevel 1 (
    echo [Birdmark API] Failed to create .venv.
    pause
    exit /b 1
  )
)

echo [Birdmark API] Checking dependencies...
"%PY%" -c "import fastapi, uvicorn, multipart, httpx, PIL" >nul 2>&1
if errorlevel 1 (
  echo [Birdmark API] Installing API dependencies...
  "%PY%" -m pip install -r apps\api\requirements.txt
  if errorlevel 1 (
    echo [Birdmark API] Failed to install API dependencies.
    pause
    exit /b 1
  )
)

if /I "%BIRDMARK_CHECK_ONLY%"=="1" (
  echo [Birdmark API] Preflight checks passed.
  exit /b 0
)

echo [Birdmark API] Starting business API at %URL% ...
"%PY%" -m uvicorn apps.api.app.main:app --host %HOST% --port %PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [Birdmark API] Service stopped.
pause
exit /b %EXIT_CODE%
