// Browser side of the Gemini Live relay (backend/app/voice/live.py).
// Mic -> PCM16 16 kHz -> WebSocket; WebSocket -> PCM16 24 kHz -> speakers. Always listening, interruptible.
import { API } from "./api";
import type { ToolCall, VoiceState } from "./voice";

const IN_RATE = 16000;

const WORKLET = `
class Pcm extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Int16Array(1600); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice().buffer); this.n = 0; }
    }
    return true;
  }
}
registerProcessor("pcm", Pcm);`;

export type LiveEvents = {
  onUser: (text: string, final: boolean) => void;
  onAiDelta: (text: string) => void;
  onAiDone: (text: string) => void;
  onTool: (call: ToolCall, state: VoiceState) => void;
  onError: (msg: string) => void;
  onClose: () => void;
};

export class LiveVoice {
  private ws?: WebSocket;
  private ctx?: AudioContext;
  private stream?: MediaStream;
  private sources: AudioBufferSourceNode[] = [];
  private next = 0;
  constructor(private ev: LiveEvents) {}

  async start() {
    this.ctx = new AudioContext({ sampleRate: IN_RATE });
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await this.ctx.audioWorklet.addModule(url);
    const node = new AudioWorkletNode(this.ctx, "pcm");
    this.ctx.createMediaStreamSource(this.stream).connect(node);

    this.ws = new WebSocket(API.replace(/^http/, "ws") + "/api/voice/live");
    this.ws.onclose = () => { this.cleanup(); this.ev.onClose(); };
    this.ws.onerror = () => this.ev.onError("Could not connect to the voice backend");
    this.ws.onmessage = (m) => this.handle(JSON.parse(m.data));
    node.port.onmessage = (e) => { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data); };
  }

  sendText(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "text", text }));
  }

  emergencyStop() {
    this.flush();
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "stop" }));
  }

  stop() {
    this.ws?.close();
    this.cleanup();
  }

  private cleanup() {
    this.flush();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = undefined;
    this.ctx = undefined;
  }

  private flush() {
    this.sources.forEach((s) => { try { s.stop(); } catch { /* already ended */ } });
    this.sources = [];
    this.next = 0;
  }

  private play(b64: string, rate: number) {
    if (!this.ctx) return;
    const bin = atob(b64);
    const pcm = new Int16Array(bin.length >> 1);
    for (let i = 0; i < pcm.length; i++) pcm[i] = (bin.charCodeAt(2 * i + 1) << 8) | bin.charCodeAt(2 * i);
    const buf = this.ctx.createBuffer(1, pcm.length, rate);
    const f = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 0x8000;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    this.next = Math.max(this.next, this.ctx.currentTime + 0.02);
    src.start(this.next);
    this.next += buf.duration;
    this.sources.push(src);
    src.onended = () => { this.sources = this.sources.filter((s) => s !== src); };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private handle(d: any) {
    switch (d.type) {
      case "audio": this.play(d.delta, d.rate ?? 24000); break;
      case "interrupt": this.flush(); break;
      case "user_partial": this.ev.onUser(d.text, false); break;
      case "user_text": this.ev.onUser(d.text, true); break;
      case "ai_delta": this.ev.onAiDelta(d.text); break;
      case "ai_done": this.ev.onAiDone(d.text); break;
      case "tool": this.ev.onTool({ name: d.name, args: d.args, result: d.result }, d.state); break;
      case "error": this.ev.onError(d.message); break;
    }
  }
}
