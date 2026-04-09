PDF Extractor - Extrator de Cartão Ponto
========================================

Este programa extrai informações de cartão ponto de arquivos PDF e salva em formato CSV,
facilitando a importação para planilhas Excel.

Requisitos:
-----------
- Python 3.8 ou superior
- Bibliotecas: pymupdf, pandas (instaladas automaticamente pelos scripts de instalação)

Instalação:
-----------
Windows:
1. Certifique-se de ter o Python instalado (https://www.python.org/downloads/)
2. Execute o arquivo "instalar_pdf_extractor.bat"
3. Aguarde a instalação das dependências

Linux:
1. Abra um terminal na pasta do programa
2. Execute: ./instalar_pdf_extractor.sh
3. Aguarde a instalação das dependências

Uso:
----
1. Execute o arquivo PDF_Extractor.py (clique duas vezes ou via terminal)
2. Selecione o arquivo PDF do cartão ponto quando solicitado
3. Escolha onde salvar o arquivo CSV resultante
4. O programa extrairá automaticamente as informações de data, entrada e saída

Observações:
------------
- O programa foi projetado para funcionar com o formato específico de cartão ponto
- O CSV gerado pode ser importado diretamente para o Excel ou outras planilhas
- Para usar com a planilha HORAS.xlsm, siga as instruções fornecidas anteriormente
