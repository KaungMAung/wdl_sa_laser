@echo off
setlocal
cd /d "%~dp0"

rem Reuse an already-running backend; api_main.py's ownership lock is final.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:8765/health; $ok=($r.StatusCode -eq 200) } catch {}; if (-not $ok) { Start-Process -FilePath python -ArgumentList 'api_main.py' -WorkingDirectory '%~dp0' -WindowStyle Normal }; for($i=0;$i -lt 30;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:8765/health; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
    echo Backend did not become ready. Check logs\lasermaker_backend.log.
    exit /b 1
)
python gui_main.py
endlocal
