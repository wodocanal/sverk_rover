@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0flash_waveshare_audio_windows.ps1" %*
exit /b %ERRORLEVEL%
