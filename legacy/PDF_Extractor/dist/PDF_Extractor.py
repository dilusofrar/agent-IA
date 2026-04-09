#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extrator de Cartão Ponto PDF
----------------------------
Este script extrai informações de cartão ponto de arquivos PDF e salva em CSV.
Desenvolvido para facilitar a importação de dados para planilhas Excel.

Instruções:
1. Execute este script
2. Selecione o arquivo PDF do cartão ponto quando solicitado
3. Escolha onde salvar o arquivo CSV resultante
"""

import re
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

# Verificar se as dependências estão instaladas
try:
    import fitz  # PyMuPDF
    import pandas as pd
except ImportError:
    # Se as dependências não estiverem instaladas, mostrar mensagem e instalar
    root = tk.Tk()
    root.withdraw()
    
    resposta = messagebox.askyesno(
        "Dependências Necessárias",
        "Este programa precisa instalar algumas bibliotecas Python para funcionar.\n\n"
        "Deseja instalar as dependências necessárias agora?\n"
        "(Isso pode levar alguns minutos e requer conexão com a internet)"
    )
    
    if resposta:
        import subprocess
        import sys
        
        # Instalar as dependências
        print("Instalando dependências...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf", "pandas"])
        
        # Tentar importar novamente
        import fitz
        import pandas as pd
        
        messagebox.showinfo("Instalação Concluída", "Dependências instaladas com sucesso!")
    else:
        messagebox.showerror("Erro", "Não é possível continuar sem as dependências necessárias.")
        sys.exit(1)

def extract_pdf():
    # Abrir diálogo para selecionar arquivo PDF
    root = tk.Tk()
    root.withdraw()  # Esconder a janela principal
    
    pdf_path = filedialog.askopenfilename(
        title="Selecione o arquivo PDF do cartão ponto",
        filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")]
    )
    
    if not pdf_path:
        messagebox.showinfo("Cancelado", "Nenhum arquivo foi selecionado.")
        return
    
    try:
        # Abrir o PDF e extrair o texto
        doc = fitz.open(pdf_path)
        text = "".join([page.get_text() for page in doc])
        
        # Regex para capturar apenas data, entrada e saída
        pattern = re.compile(
            r"(?P<dia>\d{2})\s\w{3}\s\d{4}\s\w{2}\s(?P<entrada>\d{2}:\d{2})\s[o|i]\s\d{2}:\d{2}\sp\s\d{2}:\d{2}\sp\s(?P<saida>\d{2}:\d{2})\s[o|i]"
        )
        
        # Lista para armazenar resultados
        batidas = []
        
        for match in pattern.finditer(text):
            dia = match.group("dia")
            entrada = match.group("entrada")
            saida = match.group("saida")
            mes = "04" if int(dia) >= 16 else "05"  # Lógica para determinar o mês
            data_formatada = f"2025-{mes}-{dia}"
            data_excel = datetime.strptime(data_formatada, "%Y-%m-%d").strftime("%d/%b").lower()
            batidas.append({
                "Data": data_excel,
                "Entrada": entrada,
                "Saída": saida
            })
        
        if not batidas:
            messagebox.showerror("Erro", "Nenhum registro de ponto encontrado no PDF. Verifique se o formato do arquivo é compatível.")
            return
        
        # Criar DataFrame
        df = pd.DataFrame(batidas)
        
        # Solicitar local para salvar o CSV
        csv_path = filedialog.asksaveasfilename(
            title="Salvar arquivo CSV",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV", "*.csv"), ("Todos os arquivos", "*.*")],
            initialfile="cartao_ponto_extraido.csv"
        )
        
        if not csv_path:
            messagebox.showinfo("Cancelado", "Operação cancelada pelo usuário.")
            return
        
        # Salvar como CSV
        df.to_csv(csv_path, index=False)
        
        messagebox.showinfo("Sucesso", f"Extração concluída com sucesso!\n\n{len(batidas)} registros extraídos e salvos em:\n{csv_path}")
        
    except Exception as e:
        messagebox.showerror("Erro", f"Ocorreu um erro durante a extração:\n\n{str(e)}")

if __name__ == "__main__":
    extract_pdf()
