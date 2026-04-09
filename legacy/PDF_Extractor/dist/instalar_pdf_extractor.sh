#!/bin/bash

echo "Instalando PDF Extractor..."
echo

# Verificar se o Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "Python 3 não encontrado! Por favor, instale o Python 3.8 ou superior."
    echo "Em sistemas baseados em Debian/Ubuntu, você pode instalar com:"
    echo "sudo apt-get install python3 python3-pip"
    exit 1
fi

# Instalar dependências
echo "Instalando dependências necessárias..."
python3 -m pip install --upgrade pip
python3 -m pip install pymupdf pandas

# Tornar o script executável
chmod +x PDF_Extractor.py

echo
echo "Instalação concluída!"
echo
echo "Para executar o PDF Extractor, use o comando:"
echo "python3 PDF_Extractor.py"
echo
echo "Ou torne o arquivo executável e clique duas vezes nele:"
echo "chmod +x PDF_Extractor.py"
