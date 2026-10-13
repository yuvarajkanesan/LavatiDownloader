@echo off
rem Builds dist\Lavati Downloader\ (one-folder, trimmed) and, when Inno Setup is installed, dist\LavatiDownloader-Setup.exe
rem Code signing: set SIGN_CERT_SHA1=<thumbprint> (or SIGN_PFX + SIGN_PFX_PASSWORD); see tools\sign.ps1.
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
%PY% -m pip install --quiet -e ".[dev,build]" || goto :err
%PY% -m pytest -q || goto :err
%PY% -m PyInstaller "Lavati Downloader.spec" --noconfirm --clean || goto :err
call :trim
call :sign "dist\Lavati Downloader\Lavati Downloader.exe" || goto :err
echo Built: dist\Lavati Downloader\Lavati Downloader.exe

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if defined ISCC (
  "%ISCC%" installer.iss || goto :err
  call :sign dist\LavatiDownloader-Setup.exe || goto :err
  echo Installer: dist\LavatiDownloader-Setup.exe
  powershell -NoProfile -Command "Get-FileHash dist\LavatiDownloader-Setup.exe -Algorithm SHA256 | Format-List Hash"
) else (
  echo Inno Setup not found - skipping installer. Install it from https://jrsoftware.org/isdl.php and re-run.
)
exit /b 0

:trim
rem drop Qt files the app never loads: translations, QML, unused image/platform plugins, software GL
set I=dist\Lavati Downloader\_internal\PySide6
rmdir /s /q "%I%\translations" "%I%\qml" "%I%\plugins\generic" "%I%\plugins\networkinformation" "%I%\plugins\tls" "%I%\plugins\iconengines" 2>nul
del /q "%I%\opengl32sw.dll" "%I%\Qt6Pdf.dll" "%I%\Qt6Qml*.dll" "%I%\Qt6Quick*.dll" "%I%\Qt6OpenGL*.dll" "%I%\Qt6Svg.dll" "%I%\Qt6VirtualKeyboard*.dll" 2>nul
del /q "%I%\plugins\platforms\qdirect2d.dll" "%I%\plugins\platforms\qminimal.dll" "%I%\plugins\platforms\qoffscreen.dll" 2>nul
exit /b 0

:sign
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\sign.ps1" %1
exit /b %errorlevel%

:err
echo Build failed.
exit /b 1
