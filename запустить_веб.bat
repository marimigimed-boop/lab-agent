@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================
echo   ЛАБ-АГЕНТ - Запуск веб-интерфейса
echo ================================================
echo.
echo Запускаю... подождите 5 секунд...
echo.

REM Запускаем streamlit в фоне
start "Streamlit" /MIN py -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false --server.headless true

REM Ждём пока стартует
ping -n 6 127.0.0.1 > nul

REM Открываем браузер
start http://localhost:8501

echo Браузер открыт! Адрес: http://localhost:8501
echo.
echo Не закрывайте окно "Streamlit" которое появилось.
echo Когда закончите - закройте оба окна.
echo.
pause
