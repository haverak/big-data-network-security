@echo off
setlocal EnableExtensions
chcp 65001 >nul

pushd "%~dp0"
if errorlevel 1 goto workspace_error

echo.
echo Подготовка проекта «Системы больших данных».
echo Рабочая папка: "%CD%"
echo.

if not exist "requirements.txt" goto incomplete_project
if not exist "requirements-lock.txt" goto incomplete_project
if not exist "scripts\install_dependencies.py" goto incomplete_project
if exist ".venv\Scripts\python.exe" goto install_packages

where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if errorlevel 1 goto try_python
set "BD_PYTHON=py -3.12"
goto create_environment

:try_python
where python >nul 2>&1
if errorlevel 1 goto python_missing
python -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if errorlevel 1 goto python_missing
set "BD_PYTHON=python"

:create_environment
echo Создаётся отдельное окружение Python 3.12 в папке .venv...
%BD_PYTHON% -m venv ".venv"
if errorlevel 1 goto environment_error

:install_packages
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
if errorlevel 1 goto environment_error
echo Устанавливаются фиксированные зависимости из requirements-lock.txt...
echo Источник пакетов — официальный PyPI. Контрольные суммы проверяются автоматически.
".venv\Scripts\python.exe" "scripts\install_dependencies.py"
if errorlevel 1 goto dependency_error

if exist "data\raw\kddcup99_csv.csv" goto prepare_data
echo Исходный CSV отсутствует. Пробуется публичная загрузка датасета...
".venv\Scripts\python.exe" -m analysis.download
if errorlevel 1 goto download_error
if not exist "data\raw\kddcup99_csv.csv" goto download_error

:prepare_data
echo Выполняется обработка данных. Исходный CSV не перезаписывается.
".venv\Scripts\python.exe" -m analysis.pipeline --force
if errorlevel 1 goto pipeline_error

echo.
echo Подготовка завершена. Для запуска откройте start_app.cmd.
echo Адрес приложения: http://127.0.0.1:8501
set "BD_EXIT_CODE=0"
goto finish

:python_missing
echo.
echo ОШИБКА: не найден работающий Python 3.12.
echo Установите Python 3.12 для Windows с https://www.python.org/downloads/windows/
echo При установке добавьте Python в PATH или установите Python Launcher.
echo После установки повторно откройте setup_windows.cmd.
set "BD_EXIT_CODE=1"
goto finish

:environment_error
echo.
echo ОШИБКА: не удалось создать или запустить окружение Python 3.12.
echo Если .venv осталась от другой папки или версии Python, закройте приложение,
echo удалите только папку .venv внутри этого проекта и повторите настройку.
echo Исходные данные в data\raw удалять не нужно. Подробности — в README.md.
set "BD_EXIT_CODE=1"
goto finish

:dependency_error
echo.
echo ОШИБКА: установка зависимостей не завершена.
echo Проверьте подключение к Интернету и сообщение установщика выше.
echo Затем повторно запустите setup_windows.cmd. Защиту Windows отключать не нужно.
set "BD_EXIT_CODE=1"
goto finish

:download_error
echo.
echo ОШИБКА: исходные данные не удалось получить автоматически.
echo Откройте README.md, раздел «Если данные отсутствуют», и скачайте набор
echo со страницы Kaggle вручную, используя только собственную учётную запись.
echo Поместите kddcup99_csv.csv в data\raw и повторите setup_windows.cmd.
set "BD_EXIT_CODE=1"
goto finish

:pipeline_error
echo.
echo ОШИБКА: подготовка данных не завершена. Причина показана выше.
echo Убедитесь, что data\raw\kddcup99_csv.csv относится к указанному Kaggle-набору.
echo Не исправляйте исходный CSV вручную. См. README.md и сведения о данных.
set "BD_EXIT_CODE=1"
goto finish

:incomplete_project
echo.
echo ОШИБКА: отсутствует список зависимостей или scripts\install_dependencies.py.
echo Распакуйте весь архив проекта
echo в отдельную папку и запускайте setup_windows.cmd из этой папки.
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
