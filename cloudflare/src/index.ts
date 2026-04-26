import { Container, getContainer } from "@cloudflare/containers";

type Env = {
  APP_CONTAINER: DurableObjectNamespace<AgentIaPontoContainer>;
  PORT?: string;
  PYTHONPATH?: string;
  ENABLE_API_DOCS?: string;
  ADMIN_USERNAME?: string;
  ADMIN_PASSWORD?: string;
  ADMIN_SESSION_SECRET?: string;
  APP_SESSION_SECRET?: string;
  D1_ACCOUNT_ID?: string;
  D1_DATABASE_ID?: string;
  D1_API_TOKEN?: string;
  D1_API_BASE_URL?: string;
  R2_ENDPOINT_URL?: string;
  R2_BUCKET_NAME?: string;
  R2_ACCESS_KEY_ID?: string;
  R2_SECRET_ACCESS_KEY?: string;
  R2_REGION?: string;
};

const DEFAULT_CONTAINER_PORT = "8000";
const PRIMARY_INSTANCE_NAME = "primary";

export class AgentIaPontoContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "10m";
  pingEndpoint = "localhost/healthz";
}

function compactEnv(values: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values).filter((entry): entry is [string, string] => Boolean(entry[1]))
  );
}

function buildContainerEnv(env: Env): Record<string, string> {
  return compactEnv({
    PORT: env.PORT ?? DEFAULT_CONTAINER_PORT,
    PYTHONPATH: env.PYTHONPATH ?? "/app/src",
    ENABLE_API_DOCS: env.ENABLE_API_DOCS ?? "false",
    ADMIN_USERNAME: env.ADMIN_USERNAME,
    ADMIN_PASSWORD: env.ADMIN_PASSWORD,
    ADMIN_SESSION_SECRET: env.ADMIN_SESSION_SECRET,
    APP_SESSION_SECRET: env.APP_SESSION_SECRET,
    D1_ACCOUNT_ID: env.D1_ACCOUNT_ID,
    D1_DATABASE_ID: env.D1_DATABASE_ID,
    D1_API_TOKEN: env.D1_API_TOKEN,
    D1_API_BASE_URL: env.D1_API_BASE_URL,
    R2_ENDPOINT_URL: env.R2_ENDPOINT_URL,
    R2_BUCKET_NAME: env.R2_BUCKET_NAME,
    R2_ACCESS_KEY_ID: env.R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY: env.R2_SECRET_ACCESS_KEY,
    R2_REGION: env.R2_REGION ?? "auto"
  });
}

async function getPrimaryContainer(env: Env) {
  const container = getContainer(env.APP_CONTAINER, PRIMARY_INSTANCE_NAME);
  await container.startAndWaitForPorts({
    ports: 8000,
    startOptions: {
      envVars: buildContainerEnv(env)
    },
    cancellationOptions: {
      portReadyTimeoutMS: 45_000
    }
  });
  return container;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = await getPrimaryContainer(env);
    return container.fetch(request);
  }
} satisfies ExportedHandler<Env>;
