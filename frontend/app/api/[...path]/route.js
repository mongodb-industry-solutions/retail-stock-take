// Runtime proxy: reads BACKEND_URL at request time, not build time.
// Replaces next.config.mjs rewrites() which are baked at docker build.
const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

async function proxy(request, { params }) {
  const { path } = await params;
  const destUrl = new URL(`/api/${path.join("/")}`, BACKEND);
  destUrl.search = new URL(request.url).search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");

  const init = { method: request.method, headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }

  const res = await fetch(destUrl.toString(), init);
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: res.headers,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
