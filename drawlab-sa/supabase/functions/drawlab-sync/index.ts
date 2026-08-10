import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const DEFAULT_SOURCE_BASE = "https://raw.githubusercontent.com/Mr-Meow-ZA/yeet/master/drawlab-sa";
const JSON_HEADERS = {
  "content-type": "application/json",
  "cache-control": "no-store",
};

function response(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function digest(value: string) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

async function secureEqual(left: string, right: string) {
  const [a, b] = await Promise.all([digest(left), digest(right)]);
  if (a.length !== b.length) return false;
  let different = 0;
  for (let index = 0; index < a.length; index += 1) different |= a[index] ^ b[index];
  return different === 0;
}

async function requireAutomationCredential(req: Request) {
  const expected = Deno.env.get("DRAWLAB_SYNC_TOKEN")?.trim() ?? "";
  const supplied = req.headers.get("x-drawlab-sync-token")?.trim() ?? "";
  if (!expected || !supplied) return false;
  return await secureEqual(supplied, expected);
}

const sourceBase = (Deno.env.get("DRAWLAB_SOURCE_BASE")?.trim() || DEFAULT_SOURCE_BASE).replace(/\/$/u, "");

async function source(path: string) {
  const url = `${sourceBase}/${path}?v=${Date.now()}`;
  const res = await fetch(url, {
    headers: {
      "user-agent": "DrawLab-v3-Supabase-Sync/2.0",
      "cache-control": "no-cache",
    },
  });
  if (!res.ok) throw new Error(`source_fetch_failed:${path}:${res.status}`);
  return await res.json();
}

async function optionalSource(path: string, fallback: unknown) {
  try {
    return await source(path);
  } catch {
    return fallback;
  }
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return response(405, { ok: false, error: "method_not_allowed" });
  }

  if (!(await requireAutomationCredential(req))) {
    return response(401, { ok: false, error: "unauthorized" });
  }

  try {
    const [history, cloud, research, retrospective, shadow, ev] = await Promise.all([
      source("data/historical-results.json"),
      source("data/cloud-state.json"),
      source("data/research-state.json"),
      source("v3/data/retrospective.json"),
      source("data/shadow-state.json"),
      optionalSource("data/ev-state.json", {
        model_version: "EV Hunter v1.0",
        status: "initializing",
        current: {},
        shadow_tickets: [],
        updated_at: new Date().toISOString(),
      }),
    ]);

    if (
      !Array.isArray(history?.results) ||
      !Array.isArray(cloud?.virtual?.tickets) ||
      !Array.isArray(research?.walk_forward) ||
      !retrospective?.summary ||
      !Array.isArray(shadow?.tickets) ||
      typeof ev !== "object"
    ) {
      throw new Error("source_payload_validation_failed");
    }

    const client = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
      { auth: { persistSession: false, autoRefreshToken: false } },
    );

    const { data, error } = await client.rpc("drawlab_sync_full_payload", {
      payload: { history, cloud, research, retrospective, shadow, ev },
    });
    if (error) throw error;

    return response(200, {
      ok: true,
      source: sourceBase,
      sync: data,
    });
  } catch (error) {
    return response(500, {
      ok: false,
      error: String((error as Error)?.message || error),
    });
  }
});
