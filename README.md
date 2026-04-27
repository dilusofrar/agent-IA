# Agent IA Ponto

Aplicacao web moderna para processamento de registros de ponto a partir de PDFs.
O projeto reaproveita a logica validada no fluxo anterior, mas agora entrega upload
simples, apuracao automatica, destaque de inconsistencias e exportacao em PDF.

## Estrutura

```text
agent-IA/
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
- leitura da jornada por codigo `JRND` diretamente do cartao
- calculo automatico entre jornada normal e jornada de compensacao
- separacao das horas extras antes e depois do almoco
- classificacao de extras em folgas como `extra paga`
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
- `cloudflare/wrangler.jsonc`

### Cloudflare Containers

O caminho principal de producao agora passa a ser Cloudflare:

- Worker como borda publica
- Container executando a aplicacao Python atual
- D1 como banco principal
- R2 como armazenamento principal

Arquivos principais:

- `cloudflare/wrangler.jsonc`
- `cloudflare/src/index.ts`
- `docs/cloudflare-containers-migration.md`

Fluxo resumido:

1. Ativar Workers Paid e Containers na conta
2. Configurar o projeto com diretorio raiz `/cloudflare`
3. Definir no build:

```text
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

4. Definir em runtime os secrets do app:

```text
ADMIN_USERNAME
ADMIN_PASSWORD
ADMIN_SESSION_SECRET
APP_SESSION_SECRET
D1_ACCOUNT_ID
D1_DATABASE_ID
D1_API_TOKEN
R2_ENDPOINT_URL
R2_BUCKET_NAME
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_REGION
```

5. Rodar o primeiro deploy do Worker/Container
6. Validar `healthz`, login, admin, D1 e R2
7. Cortar o trafego do dominio para a Cloudflare e, apos estabilizacao, desligar o Render

Consulte:

- [docs/cloudflare-containers-migration.md](/D:/diegoluks/CONFERIR%20PONTO/docs/cloudflare-containers-migration.md)

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

Observacao:

- O Render agora deve ser tratado como legado/rollback ate a migracao completa para Cloudflare Containers.

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

Existe tambem um runner experimental por Excel/COM em `scripts/testar_macro_planilha.vbs`, mas nesta maquina o Office esta rejeitando chamadas COM de forma intermitente.

## Regras implementadas

- leitura da jornada por codigo `JRND` no proprio espelho do ponto
- suporte a meses com jornadas mistas, como `0004 = 08:00-17:00` e `0048 = 07:45-17:00`
- calculo separado de extra antes do almoco e extra apos o almoco
- atrasos e saidas antecipadas conforme a jornada aplicada naquele dia
- horas em sabados, domingos, feriados e folgas com batida classificadas como `extra paga`
- identificacao de feriados nacionais por calendario anual
- identificacao de dias uteis sem batida ou com batidas insuficientes

## Observacoes sobre o ambiente

A `.venv` atual foi criada apontando para um Python antigo fora desta maquina/pasta. Se houver erro ao executar `.\.venv\Scripts\python.exe`, recrie o ambiente virtual com o Python instalado localmente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```
