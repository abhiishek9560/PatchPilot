const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export default {
  async fetch(request) {
    const backend = process.env.PATCHPILOT_API_URL;
    if (!backend) {
      return Response.json({ detail: "PATCHPILOT_API_URL is not configured" }, { status: 503 });
    }

    let backendUrl;
    try {
      backendUrl = new URL(backend);
      if (!['http:', 'https:'].includes(backendUrl.protocol)) throw new Error('invalid protocol');
    } catch (_error) {
      return Response.json({ detail: "PATCHPILOT_API_URL is invalid" }, { status: 503 });
    }

    const incoming = new URL(request.url);
    const upstreamPath = incoming.searchParams.get("upstream");
    if (!upstreamPath?.startsWith("/api/")) {
      return Response.json({ detail: "Invalid API proxy path" }, { status: 400 });
    }
    incoming.searchParams.delete("upstream");

    const target = new URL(upstreamPath, backendUrl);
    if (!target.pathname.startsWith("/api/")) {
      return Response.json({ detail: "Invalid API proxy path" }, { status: 400 });
    }
    target.search = incoming.searchParams.toString();

    const headers = new Headers(request.headers);
    for (const header of HOP_BY_HOP_HEADERS) headers.delete(header);
    headers.set("x-forwarded-host", incoming.host);
    headers.set("x-forwarded-proto", "https");

    const options = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    if (!["GET", "HEAD"].includes(request.method)) {
      options.body = await request.arrayBuffer();
    }

    let response;
    try {
      response = await fetch(target, options);
    } catch (_error) {
      return Response.json({ detail: "PatchPilot API is unavailable" }, { status: 502 });
    }
    const responseHeaders = new Headers(response.headers);
    for (const header of HOP_BY_HOP_HEADERS) responseHeaders.delete(header);
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  },
};
