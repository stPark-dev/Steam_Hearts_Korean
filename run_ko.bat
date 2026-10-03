@echo off
rem 스팀하츠 한글판 실행 (Windows) - out\ko 를 먼저 빌드: python tools\khpatch.py build --source "원본.cue"
chcp 65001 >nul
cd /d "%~dp0"
set "MEDNAFEN_HOME=%CD%\work\mednafen_home"
if not exist "%MEDNAFEN_HOME%\firmware" mkdir "%MEDNAFEN_HOME%\firmware"
if not exist "%MEDNAFEN_HOME%\firmware\sega_101.bin" copy /y sega_101.bin "%MEDNAFEN_HOME%\firmware\" >nul
"work\tools\mednafen-win\mednafen.exe" -sound 1 -video.fs 0 %* "out\ko\Steam-Hearts (Korean).cue"
if errorlevel 1 pause
