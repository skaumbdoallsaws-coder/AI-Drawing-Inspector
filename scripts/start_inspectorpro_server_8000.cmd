@echo off
cd /d "%~dp0.."
echo [%date% %time%] starting InspectorPro server from %cd% >> uvicorn_facility_launcher.log
"C:\Python314\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000 >> uvicorn_facility.out.log 2>> uvicorn_facility.err.log
echo [%date% %time%] InspectorPro server exited with code %errorlevel% >> uvicorn_facility_launcher.log
