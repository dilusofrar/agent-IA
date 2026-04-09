# Conferencia de Registro de Ponto

Projeto reorganizado para manter separado o que e:

- codigo fonte
- arquivos de entrada
- arquivos gerados
- materiais antigos

## Estrutura

```text
CONFERIR PONTO/
|-- data/
|   |-- inputs/        # PDFs recebidos
|   |-- outputs/       # CSVs e planilhas geradas
|   `-- templates/     # planilhas modelo
|-- docs/              # VBA e instrucoes operacionais
|-- legacy/            # versoes antigas preservadas
|-- scripts/           # pontos de entrada de execucao
|-- src/               # regra de negocio Python
|-- pdf_extractor.py   # atalho compativel com o fluxo antigo
`-- requirements.txt
```

## Fluxo do projeto

1. Coloque o PDF do cartao ponto em `data/inputs/`.
2. Execute o extrator Python.
3. O CSV sera gerado em `data/outputs/`.
4. Importe o CSV na planilha Excel usando o macro em `docs/vba_importar_pontos.bas`.

## Como executar

### Opcao 1: manter o comando antigo

```powershell
python .\pdf_extractor.py
```

### Opcao 2: usar o script novo

```powershell
python .\scripts\extrair_cartao_ponto.py
```

### Informando arquivos manualmente

```powershell
python .\scripts\extrair_cartao_ponto.py .\data\inputs\DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO.pdf -o .\data\outputs\meu_cartao.csv
```

## Teste automatizado da planilha

Para validar o preenchimento da planilha de forma automatizada:

```powershell
py .\scripts\testar_macro_planilha.py
```

Esse script:

- abre a planilha `.xlsm` preservando as macros
- aplica na planilha a mesma regra de preenchimento do macro
- salva o resultado em `data/outputs/HORAS_teste_macro.xlsm`
- mostra algumas datas validadas com entrada e saida preenchidas

Existe tambem um runner experimental por Excel/COM em [scripts/testar_macro_planilha.vbs](D:/diegoluks/CONFERIR%20PONTO/scripts/testar_macro_planilha.vbs), mas nesta maquina o Office esta rejeitando chamadas COM de forma intermitente.

## Melhorias aplicadas

- remocao de caminhos fixos em disco
- remocao da logica hardcoded de mes e ano
- parser centralizado em modulo reutilizavel
- escrita de CSV sem depender de pandas
- compatibilidade mantida com `pdf_extractor.py`
- organizacao dos arquivos de exemplo e artefatos antigos

## Observacoes sobre o ambiente

A `.venv` atual foi criada apontando para um Python antigo fora desta maquina/pasta. Se houver erro ao executar `.\.venv\Scripts\python.exe`, recrie o ambiente virtual com o Python instalado localmente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```
