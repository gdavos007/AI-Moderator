import http from "node:http";
import { randomUUID } from "node:crypto";
import { URL } from "node:url";

const port = process.env.PORT ? Number(process.env.PORT) : 4000;

const sessions = new Map();

const jsonResponse = (res, status, payload) => {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  });
  res.end(JSON.stringify(payload));
};

const readBody = async (req) => {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  if (!chunks.length) {
    return null;
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf-8"));
  } catch (error) {
    return null;
  }
};

const getSession = (sessionId) => sessions.get(sessionId);

const createSession = (roomName) => {
  const sessionId = randomUUID();
  const session = {
    id: sessionId,
    roomName,
    status: "waiting",
    events: []
  };
  sessions.set(sessionId, session);
  return session;
};

const server = http.createServer(async (req, res) => {
  const requestUrl = new URL(req.url ?? "/", `http://${req.headers.host}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    });
    res.end();
    return;
  }

  if (req.method === "POST" && requestUrl.pathname === "/api/sessions") {
    const body = await readBody(req);
    const roomName = body?.roomName ?? "leverai-demo";
    const session = createSession(roomName);
    jsonResponse(res, 201, session);
    return;
  }

  const sessionMatch = requestUrl.pathname.match(
    /^\/api\/sessions\/([^/]+)(?:\/(start|end|raise-hand))?$/
  );

  if (!sessionMatch) {
    jsonResponse(res, 404, { error: "Not found" });
    return;
  }

  const [, sessionId, action] = sessionMatch;
  const session = getSession(sessionId);

  if (!session) {
    jsonResponse(res, 404, { error: "Session not found" });
    return;
  }

  if (req.method === "POST" && action === "start") {
    session.status = "in_session";
    jsonResponse(res, 200, { status: session.status });
    return;
  }

  if (req.method === "POST" && action === "end") {
    session.status = "ended";
    jsonResponse(res, 200, { status: session.status });
    return;
  }

  if (req.method === "POST" && action === "raise-hand") {
    const eventPayload = await readBody(req);
    if (!eventPayload?.version || eventPayload.type !== "raise_hand") {
      jsonResponse(res, 400, { error: "Invalid event payload" });
      return;
    }
    session.events.push(eventPayload);
    jsonResponse(res, 202, { accepted: true, queuePosition: session.events.length });
    return;
  }

  jsonResponse(res, 405, { error: "Method not allowed" });
});

server.listen(port, () => {
  // eslint-disable-next-line no-console
  console.log(`LeverAI API listening on http://localhost:${port}`);
});
