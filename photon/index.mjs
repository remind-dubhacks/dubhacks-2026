// Tiny HTTP bridge: the Python backend POSTs {to, text} and this sends it as an iMessage through Photon
// (Spectrum). Needs SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET from app.photon.codes.
import http from "node:http";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const PORT = Number(process.env.PHOTON_PORT ?? 8002);
const { SPECTRUM_PROJECT_ID: projectId, SPECTRUM_PROJECT_SECRET: projectSecret } = process.env;

// Free/Pro projects can only text enrolled people, and the line they text on is assigned by Photon. The reliable
// way in is to reply into a conversation the person started, so we remember a space per sender as they text us.
const spaces = new Map(); // "+1206…" -> space
let im = null;
let starting = null;

function start() {
  starting ??= (async () => {
    const app = await Spectrum({ projectId, projectSecret, providers: [imessage.config()] });
    im = imessage(app);
    (async () => {
      for await (const [space, message] of app.messages) {
        const from = message.sender?.id;
        if (!from) continue;
        const first = !spaces.has(from);
        spaces.set(from, space);
        console.log(`inbound from ${from}${first ? " (conversation saved, alerts can now reach them)" : ""}`);
        if (first && message.content?.type === "text") {
          await space.send("ReMind: you'll get alerts from the companion in this chat.").catch((e) => console.error("ack failed:", e?.message));
        }
      }
    })().catch((e) => { console.error("inbound listener stopped:", e); starting = null; });
  })().catch((e) => { starting = null; throw e; });
  return starting;
}

async function send(to, text) {
  await start();
  const known = spaces.get(to);
  if (known) return known.send(text);
  try {
    const user = await im.user(to);
    const dm = await im.space.create(user);
    await dm.send(text);
  } catch (e) {
    const err = new Error(`${e?.message ?? e}. Ask ${to} to text the project's line once so alerts can reach them.`);
    throw err;
  }
}

const server = http.createServer((req, res) => {
  const reply = (code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
  if (req.method === "GET" && req.url === "/health") return reply(200, { ok: true, configured: Boolean(projectId && projectSecret) });
  if (req.method !== "POST" || req.url !== "/send") return reply(404, { ok: false });

  let raw = "";
  req.on("data", (d) => { raw += d; if (raw.length > 10_000) req.destroy(); });
  req.on("end", async () => {
    try {
      const { to, text } = JSON.parse(raw);
      if (!/^\+\d{7,15}$/.test(to ?? "") || !text) return reply(400, { ok: false, error: "need to (E.164, e.g. +15551234567) and text" });
      if (!projectId || !projectSecret) return reply(503, { ok: false, error: "SPECTRUM_PROJECT_ID / SPECTRUM_PROJECT_SECRET not set" });
      await send(to, String(text).slice(0, 600));
      reply(200, { ok: true });
    } catch (e) {
      console.error("send failed:", e);
      reply(502, { ok: false, error: String(e?.message ?? e) });
    }
  });
});

server.listen(PORT, () => { console.log(`photon bridge on :${PORT}`); if (projectId && projectSecret) start().catch((e) => console.error("start failed:", e?.message)); });
