@echo off
setlocal EnableExtensions
chcp 65001 >nul

pushd "%~dp0"
if errorlevel 1 goto workspace_error

if not exist ".venv\Scripts\python.exe" goto environment_missing
if not exist "app\main.py" goto incomplete_project
if not exist "data\raw\kddcup99_csv.csv" goto data_missing

".venv\Scripts\python.exe" -m streamlit --version >nul 2>&1
if errorlevel 1 goto environment_missing

echo.
echo Запускается аналитическое приложение.
echo Откройте в браузере: http://127.0.0.1:8501
echo Оставьте это окно открытым. Для остановки нажмите Ctrl+C.
echo.
".venv\Scripts\python.exe" -m streamlit run "app\main.py" --server.address 127.0.0.1 --server.port 8501
set "BD_EXIT_CODE=%ERRORLEVEL%"
if not "%BD_EXIT_CODE%"=="0" echo Приложение завершилось с ошибкой. Проверьте сообщение выше и раздел README.md об ошибках запуска.
goto finish

:environment_missing
echo.
echo ОШИБКА: окружение приложения не готово или отсутствует Streamlit.
echo Сначала запустите setup_windows.cmd и дождитесь успешного завершения.
set "BD_EXIT_CODE=1"
goto finish

:data_missing
echo.
echo ОШИБКА: не найден data\raw\kddcup99_csv.csv.
echo Запустите setup_windows.cmd: он попробует загрузить данные и подготовить их.
echo Если Kaggle запросит вход, следуйте разделу README.md «Если данные отсутствуют».
set "BD_EXIT_CODE=1"
goto finish

:incomplete_project
echo.
echo ОШИБКА: не найден app\main.py. Распакуйте весь ZIP, сохранив структуру папок.
set "BD_EXIT_CODE=1"
goto finish

:finish
popd
if not "%BIGDATA_NO_PAUSE%"=="1" pause
exit /b %BD_EXIT_CODE%

:workspace_error
echo ОШИБКА: не удалось открыть папку проекта. Сначала полностью распакуйте ZIP.
if not "%BIGDATA_NO_PAUSE%"=="1" pause
exit /b 1
