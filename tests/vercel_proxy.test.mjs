import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import proxy from "../api/proxy.mjs";


test("proxy preserves API requests, cookies, redirects, and response cookies", async (context) => {
  let resolveRequest;
  const receivedRequest = new Promise((resolve) => {
    resolveRequest = resolve;
  });
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    resolveRequest({
      method: request.method,
      url: request.url,
      headers: request.headers,
      body: Buffer.concat(chunks).toString("utf8"),
    });
    response.writeHead(307, {
      location: "/api/github/install",
      "set-cookie": "patchpilot_session=test-token; Path=/; HttpOnly; SameSite=Lax",
    });
    response.end();
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => new Promise((resolve) => server.close(resolve)));

  const address = server.address();
  process.env.PATCHPILOT_API_URL = `http://127.0.0.1:${address.port}`;
  const response = await proxy.fetch(
    new Request(
      "https://patchpilot.example/api/auth/login?upstream=/api/auth/login&next=dashboard",
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          cookie: "patchpilot_session=browser-token",
        },
        body: JSON.stringify({ email: "pilot@example.com" }),
      },
    ),
  );
  const received = await receivedRequest;

  assert.equal(response.status, 307);
  assert.equal(response.headers.get("location"), "/api/github/install");
  assert.match(response.headers.get("set-cookie"), /patchpilot_session=test-token/);
  assert.equal(received.method, "POST");
  assert.equal(received.url, "/api/auth/login?next=dashboard");
  assert.equal(received.headers.cookie, "patchpilot_session=browser-token");
  assert.equal(received.headers["x-forwarded-host"], "patchpilot.example");
  assert.equal(received.headers["x-forwarded-proto"], "https");
  assert.deepEqual(JSON.parse(received.body), { email: "pilot@example.com" });
});


test("proxy rejects missing, invalid, and normalized-outside-API targets", async () => {
  delete process.env.PATCHPILOT_API_URL;
  let response = await proxy.fetch(
    new Request("https://patchpilot.example/api/health?upstream=/api/health"),
  );
  assert.equal(response.status, 503);

  process.env.PATCHPILOT_API_URL = "file:///tmp/backend";
  response = await proxy.fetch(
    new Request("https://patchpilot.example/api/health?upstream=/api/health"),
  );
  assert.equal(response.status, 503);

  process.env.PATCHPILOT_API_URL = "https://api.example";
  response = await proxy.fetch(
    new Request("https://patchpilot.example/api/health?upstream=/api/../health"),
  );
  assert.equal(response.status, 400);
});
