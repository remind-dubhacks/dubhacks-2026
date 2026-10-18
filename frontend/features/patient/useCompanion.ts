"use client";

// Patient screen session: one Gemini Live conversation. Tool events carry the game state, and the
// screen shows exactly `state.screen`. Sounds wait until the AI has finished speaking, then the relay
// is told the clip ended so Gemini can ask about it.
import { useCallback, useEffect, useRef, useState } from "react";
import { LiveVoice } from "@/lib/liveVoice";
import type { Screen, VoiceState } from "@/lib/voice";

export type CompanionStatus = "setup" | "connecting" | "live";

const REST: Screen = { kind: "rest" };
const SOUND_DONE = "(The sound has finished playing.)";
const SPEECH_WAIT_MS = 6000; // give up waiting for Gemini's "Have a listen." after this
const MAX_SOUND_S = 8;

export function useCompanion() {
  const [status, setStatus] = useState<CompanionStatus>("setup");
  const [screen, setScreen] = useState<Screen>(REST);
  const [error, setError] = useState<string | null>(null);
  const liveRef = useRef<LiveVoice | null>(null);
  const soundId = useRef(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const turnDone = useRef<(() => void) | null>(null);

  const playSound = useCallback(async (src: string, id: number) => {
    const live = liveRef.current;
    if (!live) return;
    // Wait for the spoken lead-in ("Have a listen.") to finish, so the clip never plays over the voice.
    await new Promise<void>((resolve) => {
      turnDone.current = resolve;
      setTimeout(resolve, SPEECH_WAIT_MS);
    });
    turnDone.current = null;
    await live.whenIdle();
    if (soundId.current !== id || liveRef.current !== live) return; // replaced or session ended
    audioRef.current?.pause();
    const a = new Audio(src);
    audioRef.current = a;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      a.pause();
      if (soundId.current === id && liveRef.current === live) live.sendText(SOUND_DONE);
    };
    a.onended = finish;
    // Long clips are cut at MAX_SOUND_S with a one-second fade, so nothing ends abruptly.
    setTimeout(() => {
      if (done) return;
      const fade = setInterval(() => {
        a.volume = Math.max(0, a.volume - 0.1);
        if (a.volume === 0) { clearInterval(fade); finish(); }
      }, 100);
    }, (MAX_SOUND_S - 1) * 1000);
    a.onerror = () => live.sendText("(The sound could not be played. Apologise and move on.)");
    a.play().catch(() => live.sendText("(The sound could not be played. Apologise and move on.)"));
  }, []);

  const onState = useCallback((state: VoiceState) => {
    setScreen(state.screen ?? REST);
    if (state.sound && state.sound.id !== soundId.current) {
      soundId.current = state.sound.id;
      playSound(state.sound.src, state.sound.id);
    } else if (!state.sound) {
      soundId.current = 0;
      audioRef.current?.pause();
    }
  }, [playSound]);

  const end = useCallback(() => {
    audioRef.current?.pause();
    liveRef.current?.stop();
    liveRef.current = null;
    setScreen(REST);
    setStatus("setup");
  }, []);

  const start = useCallback(async (name: string, games: string[], phone = "") => {
    setError(null);
    setStatus("connecting");
    const live = new LiveVoice({
      onUser: () => {},
      onAiDelta: () => {},
      onAiDone: () => turnDone.current?.(),
      onTool: (_call, state) => onState(state),
      onError: (msg) => setError(msg),
      onClose: () => {
        if (liveRef.current === live) {
          liveRef.current = null;
          setScreen(REST);
          setStatus("setup");
        }
      },
    });
    liveRef.current = live;
    try {
      await live.start({ name, games: games.join(","), ...(phone ? { phone } : {}) });
      setStatus("live");
    } catch (e) {
      liveRef.current = null;
      setError(e instanceof Error && e.name === "NotAllowedError" ? "Microphone permission was blocked" : "Could not start the microphone");
      setStatus("setup");
    }
  }, [onState]);

  useEffect(() => () => { liveRef.current?.stop(); audioRef.current?.pause(); }, []);

  return { status, screen, error, start, end };
}
