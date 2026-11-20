// Cloudflare Worker that serves client subscription files from Workers KV.
//
// Setup: bind a KV namespace to this Worker under the variable name SUBS and
// attach a custom domain such as sub.example.com. See docs/subscriptions.md.
//
// The Worker contains no secrets. scripts/subscriptions.py uploads one file per
// person and client type; the long random file names act as secret URLs.
export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(null, {
        status: 405,
        headers: { allow: "GET, HEAD", "cache-control": "no-store" },
      });
    }

    // Only long random names are looked up. Anything else is answered with
    // 404 without a KV read, so random scanners do not use the read quota.
    const name = new URL(request.url).pathname.slice(1);
    if (!/^[A-Za-z0-9_-]{32,128}$/.test(name)) return notFound();

    const { value, metadata } = await env.SUBS.getWithMetadata(name);
    if (value === null) return notFound();

    const headers = new Headers({
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    });
    // Optional extra headers chosen by the upload script, such as the Clash
    // Verge Rev profile name and refresh interval.
    for (const [key, val] of Object.entries(metadata?.headers ?? {})) {
      headers.set(key, val);
    }

    return new Response(request.method === "HEAD" ? null : value, { headers });
  },
};

function notFound() {
  return new Response("Not found\n", {
    status: 404,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
