@echo off
echo ============================================================
echo  Установка агента moimedlab
echo ============================================================

REM Устанавливаем зависимости
echo Устанавливаю зависимости...
py -3 -m pip install anthropic pdfplumber python-dotenv

REM Проверяем наличие .env
if not exist "..\..\..\.env" (
    echo.
    echo ВНИМАНИЕ: файл .env не найден!
    echo Скопируйте .env.example в .env и заполните реальные значения.
    echo Путь: %~dp0..\..\..\.env
) else (
    echo Файл .env найден.
)

echo.
echo Установка завершена.
echo Для запуска агента выполните:
echo   py -3 moimedlab.py
echo.
pause
