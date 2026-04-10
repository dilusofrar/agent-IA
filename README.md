# Agent IA Ponto

Aplicacao web moderna para processamento de registros de ponto a partir de PDFs.
O projeto reaproveita a logica validada no fluxo anterior, mas agora entrega upload
simples, apuracao automatica, destaque de inconsistencias e exportacao em PDF.

## Estrutura

```text
CONFERIR PONTO/
|-- data/
|   |-- inputs/        # PDFs recebidos
|   |-- outputs/       # CSVs e planilhas geradas
|   `-- templates/     # planilhas modelo
|-- docs/              # VBA e referencia do fluxo antigo
|-- legacy/            # versoes antigas preservadas
|-- scripts/           # pontos de entrada de execucao
|-- src/               # regra de negocio Python
|-- web/               # interface web
|-- pdf_extractor.py   # atalho compativel com o fluxo antigo
`-- requirements.txt
```

## O que a aplicacao faz

- upload de PDF pelo navegador
- extracao automatica das batidas
- calculo da jornada padrao `07:45-17:00`, com almoco `12:00-13:00`
- separacao das horas extras antes e depois do almoco
- ignorar sabados, domingos e feriados
- destaque de dias inconsistentes
- exportacao em `.pdf`

## Como executar a aplicacao web

```powershell
py -m pip install -r requirements.txt
py .\scripts\rodar_web.py
```

Depois abra:

`http://127.0.0.1:8000`

## Deploy

O projeto esta pronto para deploy com Docker. Os arquivos principais sao:

- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `render.yaml`

### Hostinger + Cloudflare Tunnel

Se voce for usar VPS da Hostinger com DNS da Cloudflare e `cloudflared`, este e o caminho mais simples:

1. Instale `docker` e `docker compose` no VPS
2. Clone o repositorio no servidor
3. Suba a aplicacao com:

```bash
docker compose up -d --build
```

4. Verifique se a aplicacao respondeu localmente:

```bash
curl http://127.0.0.1:8000/healthz
```

5. No `cloudflared`, aponte o tunnel para:

```text
http://127.0.0.1:8000
```

Exemplo de bloco no arquivo de configuracao do tunnel:

```yaml
ingress:
  - hostname: ponto.seudominio.com.br
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Com esse desenho:

- a aplicacao nao fica exposta diretamente na internet
- o acesso externo passa pela Cloudflare
- o Docker publica apenas em `127.0.0.1:8000`

Para atualizar depois:

```bash
git pull
docker compose up -d --build
```

### Render

1. Publique o repositorio no GitHub
2. Acesse [render.com](https://render.com)
3. Crie um novo `Blueprint` ou `Web Service`
4. Conecte o repositorio `dilusofrar/agent-IA`
5. Se usar `Blueprint`, o Render vai ler automaticamente o arquivo `render.yaml`
6. Aguarde o build e abra a URL gerada

O health check fica em:

`/healthz`

## Fluxo antigo em linha de comando

### Manter o comando antigo

```powershell
python .\pdf_extractor.py
```

### Usar o script direto

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

## Regras implementadas

- jornada esperada de `8h15` por dia util
- calculo separado de extra antes do almoco e extra apos o almoco
- atrasos e saidas antecipadas por comparacao com o horario padrao
- exclusao de sabados, domingos, feriados nacionais e dias com status `FE`, `CO` e `RE`
- identificacao de dias uteis sem batida ou com batidas insuficientes

## Observacoes sobre o ambiente

A `.venv` atual foi criada apontando para um Python antigo fora desta maquina/pasta. Se houver erro ao executar `.\.venv\Scripts\python.exe`, recrie o ambiente virtual com o Python instalado localmente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```
