from pathlib import Path
import os
import sys

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


if __name__ == "__main__":
    # Em plataformas PaaS (ex.: Render), a aplicacao precisa escutar em 0.0.0.0
    # para ficar acessivel fora do container.
    host = os.getenv("HOST", "0.0.0.0")
    if os.getenv("RENDER") and host in {"127.0.0.1", "localhost"}:
        host = "0.0.0.0"
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("conferir_ponto.web:app", host=host, port=port, reload=False)
