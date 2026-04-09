@echo off
echo Instalando PDF Extractor...
echo.

:: Verificar se o Python está instalado
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Python não encontrado! Por favor, instale o Python 3.8 ou superior.
    echo Você pode baixar o Python em: https://www.python.org/downloads/
    echo.
    echo Certifique-se de marcar a opção "Add Python to PATH" durante a instalação.
    pause
    exit /b 1
)

:: Instalar dependências
echo Instalando dependências necessárias...
python -m pip install --upgrade pip
python -m pip install pymupdf pandas

echo.
echo Instalação concluída!
echo.
echo Para executar o PDF Extractor, basta clicar duas vezes no arquivo PDF_Extractor.py
echo.
pause
