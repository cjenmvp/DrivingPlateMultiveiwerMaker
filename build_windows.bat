@echo off
chcp 65001 > nul
echo ========================================================
echo CJENMVP 드라이빙플레이트 멀티뷰어 - 윈도우 빌드 스크립트
echo ========================================================

echo [1/3] Python 확인 중...
python --version
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되지 않았거나 PATH에 등록되지 않았습니다.
    echo Python 3.10 이상을 설치하고 다시 시도해주세요.
    pause
    exit /b
)

echo.
echo [2/3] 필수 라이브러리 설치 중...
pip install PySide6 ffmpeg-python pyinstaller
if %errorlevel% neq 0 (
    echo [오류] 라이브러리 설치에 실패했습니다. 인터넷 연결을 확인해주세요.
    pause
    exit /b
)

echo.
echo [3/3] 실행 파일 빌드 중...
pyinstaller --noconfirm --onedir --windowed --name "CJENMVP_Multiviewer_v1" main.py

if %errorlevel% neq 0 (
    echo [오류] 빌드 과정에서 문제가 발생했습니다.
    pause
    exit /b
)

echo.
echo ========================================================
echo [성공] 빌드가 완료되었습니다!
echo 'dist\CJENMVP_Multiviewer_v1' 폴더 안에 실행 파일이 있습니다.
echo ========================================================
pause
