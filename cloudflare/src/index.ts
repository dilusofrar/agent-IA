import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";

export { ContainerProxy };

type Env = {
  APP_CONTAINER: DurableObjectNamespace<AgentIaPontoContainer>;
  PORT?: string;
  PYTHONPATH?: string;
  ENABLE_API_DOCS?: string;
  ADMIN_USERNAME?: string;
  ADMIN_PASSWORD?: string;
  ADMIN_SESSION_SECRET?: string;
  APP_SESSION_SECRET?: string;
  D1_BINDING_NAME?: string;
  D1_ACCOUNT_ID?: string;
  D1_DATABASE_ID?: string;
  D1_API_TOKEN?: string;
  D1_API_BASE_URL?: string;
  R2_BINDING_NAME?: string;
  R2_ENDPOINT_URL?: string;
  R2_BUCKET_NAME?: string;
  R2_ACCESS_KEY_ID?: string;
  R2_SECRET_ACCESS_KEY?: string;
  R2_REGION?: string;
} & Record<string, unknown>;

const DEFAULT_CONTAINER_PORT = "8000";
const PRIMARY_INSTANCE_NAME = "primary";
const D1_OUTBOUND_HOST = "d1.binding";
const R2_OUTBOUND_HOST = "r2.binding";

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

function getNativeD1BaseUrl(env: Env): string | undefined {
  return env.D1_BINDING_NAME ? `http://${D1_OUTBOUND_HOST}` : env.D1_API_BASE_URL;
}

function getNativeR2EndpointUrl(env: Env): string | undefined {
  return env.R2_BINDING_NAME ? `http://${R2_OUTBOUND_HOST}` : env.R2_ENDPOINT_URL;
}

function buildContainerEnv(env: Env): Record<string, string> {
  const useNativeD1Binding = Boolean(env.D1_BINDING_NAME);
  const useNativeR2Binding = Boolean(env.R2_BINDING_NAME);
  return compactEnv({
    PORT: env.PORT ?? DEFAULT_CONTAINER_PORT,
    PYTHONPATH: env.PYTHONPATH ?? "/app/src",
    ENABLE_API_DOCS: env.ENABLE_API_DOCS ?? "false",
    ADMIN_USERNAME: env.ADMIN_USERNAME,
    ADMIN_PASSWORD: env.ADMIN_PASSWORD,
    ADMIN_SESSION_SECRET: env.ADMIN_SESSION_SECRET,
    APP_SESSION_SECRET: env.APP_SESSION_SECRET,
    D1_ACCOUNT_ID: useNativeD1Binding ? undefined : env.D1_ACCOUNT_ID,
    D1_DATABASE_ID: useNativeD1Binding ? undefined : env.D1_DATABASE_ID,
    D1_API_TOKEN: useNativeD1Binding ? undefined : env.D1_API_TOKEN,
    D1_API_BASE_URL: getNativeD1BaseUrl(env),
    R2_ENDPOINT_URL: getNativeR2EndpointUrl(env),
    R2_BUCKET_NAME: env.R2_BUCKET_NAME,
    R2_ACCESS_KEY_ID: useNativeR2Binding ? undefined : env.R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY: useNativeR2Binding ? undefined : env.R2_SECRET_ACCESS_KEY,
    R2_REGION: env.R2_REGION ?? "auto"
  });
}

function getD1Binding(env: Env) {
  const bindingName = env.D1_BINDING_NAME;
  if (!bindingName) {
    throw new Error("D1_BINDING_NAME is not configured.");
  }
  const binding = env[bindingName];
  if (!binding || typeof binding !== "object" || !("prepare" in binding)) {
    throw new Error(`D1 binding "${bindingName}" is unavailable.`);
  }
  return binding as D1Database;
}

function getR2Binding(env: Env) {
  const bindingName = env.R2_BINDING_NAME;
  if (!bindingName) {
    throw new Error("R2_BINDING_NAME is not configured.");
  }
  const binding = env[bindingName];
  if (!binding || typeof binding !== "object" || !("get" in binding) || !("put" in binding)) {
    throw new Error(`R2 binding "${bindingName}" is unavailable.`);
  }
  return binding as R2Bucket;
}

function isD1ReadQuery(sql: string): boolean {
  return /^\s*(select|pragma|explain|with)\b/i.test(sql);
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

AgentIaPontoContainer.outboundByHost = {
  [D1_OUTBOUND_HOST]: async (request, env) => {
    try {
      if (request.method !== "POST") {
        return Response.json(
          { success: false, errors: [{ message: "Method Not Allowed" }] },
          { status: 405 }
        );
      }
      const url = new URL(request.url);
      if (url.pathname !== "/query") {
        return Response.json(
          { success: false, errors: [{ message: "Not Found" }] },
          { status: 404 }
        );
      }
      const payload = (await request.json()) as { sql?: string; params?: unknown[] };
      const sql = String(payload.sql ?? "").trim();
      const params = Array.isArray(payload.params) ? payload.params : [];
      if (!sql) {
        return Response.json(
          { success: false, errors: [{ message: "SQL is required." }] },
          { status: 400 }
        );
      }
      let statement = getD1Binding(env).prepare(sql);
      if (params.length > 0) {
        statement = statement.bind(...params);
      }
      if (isD1ReadQuery(sql)) {
        const result = await statement.all<Record<string, unknown>>();
        return Response.json({
          success: true,
          result: [{ results: result.results ?? [] }]
        });
      }
      const result = await statement.run();
      return Response.json({
        success: true,
        result: [{ results: [], meta: result.meta }]
      });
    } catch (error) {
      return Response.json(
        { success: false, errors: [{ message: error instanceof Error ? error.message : String(error) }] },
        { status: 400 }
      );
    }
  },
  [R2_OUTBOUND_HOST]: async (request, env) => {
    try {
      const bucket = getR2Binding(env);
      const url = new URL(request.url);
      const key = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
      if (!key) {
        return new Response("Missing object key.", { status: 400 });
      }

      if (request.method === "PUT") {
        await bucket.put(key, request.body);
        return new Response(null, { status: 204 });
      }

      if (request.method === "GET") {
        const object = await bucket.get(key);
        if (!object) {
          return new Response(null, { status: 404 });
        }
        return new Response(object.body, {
          status: 200,
          headers: object.httpMetadata?.contentType
            ? { "Content-Type": object.httpMetadata.contentType }
            : undefined
        });
      }

      if (request.method === "HEAD") {
        const object = await bucket.head(key);
        return new Response(null, { status: object ? 200 : 404 });
      }

      if (request.method === "DELETE") {
        await bucket.delete(key);
        return new Response(null, { status: 204 });
      }

      return new Response("Method Not Allowed", { status: 405 });
    } catch (error) {
      return new Response(error instanceof Error ? error.message : String(error), { status: 500 });
    }
  }
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = await getPrimaryContainer(env);
    return container.fetch(request);
  }
} satisfies ExportedHandler<Env>;
