@echo off
chcp 65001 >nul
echo ========================================
echo 安装AI图片分类训练界面依赖
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8或更高版本
    pause
    exit /b 1
)

echo 正在安装基础依赖包...
pip install opencv-python Pillow numpy scikit-learn joblib

echo.
echo 正在尝试安装face-recognition（需要dlib）...
echo 注意：如果dlib安装失败，程序仍可运行，但人脸识别功能会受限
echo.

pip install face-recognition 2>nul
if errorlevel 1 (
    echo.
    echo [提示] face-recognition安装失败（通常是因为dlib需要CMake）
    echo 程序仍可运行，但人脸识别功能将使用简化版本
    echo.
    echo 如果需要完整的人脸识别功能，请：
    echo 1. 安装CMake: https://cmake.org/download/
    echo 2. 或使用conda: conda install -c conda-forge dlib
    echo 3. 然后运行: pip install face-recognition
    echo.
) else (
    echo [成功] face-recognition安装完成
)

echo.
echo ========================================
echo 依赖安装完成！
echo ========================================
echo.
pause




