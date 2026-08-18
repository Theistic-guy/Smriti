@echo off
echo Starting Smriti in debug mode...

if exist "Smriti.dist\Smriti.exe" (
    cd Smriti.dist
    Smriti.exe
) else if exist "Smriti2.dist\Smriti2.exe" (
    cd Smriti2.dist
    Smriti2.exe
) else (
    echo "Could not find the compiled Smriti.exe in Smriti.dist!"
)

echo.
echo ===========================================
echo If you see an error above, please copy it!
echo ===========================================
pause
