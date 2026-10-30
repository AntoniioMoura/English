// Sons curtos gerados no navegador (Web Audio): nada de arquivo de áudio para baixar.
// Volumes baixos de propósito — é para acompanhar a digitação, não para chamar atenção.

const STORAGE_KEY = "listening.sound";

let ctx: AudioContext | null = null;
let noise: AudioBuffer | null = null;

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

export function soundEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setSoundEnabled(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {
    /* sem armazenamento: vale só nesta visita */
  }
}

function noiseBuffer(ac: AudioContext): AudioBuffer {
  if (!noise) {
    noise = ac.createBuffer(1, Math.floor(ac.sampleRate * 0.03), ac.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 2;
  }
  return noise;
}

// "Tic" de tecla: ruído curtíssimo filtrado, como uma tecla macia.
function tick(frequency: number, volume: number) {
  const ac = audio();
  if (!ac || !soundEnabled()) return;
  const src = ac.createBufferSource();
  src.buffer = noiseBuffer(ac);
  src.playbackRate.value = 0.9 + Math.random() * 0.2; // pequena variação: soa menos mecânico
  const filter = ac.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = frequency;
  filter.Q.value = 1.2;
  const gain = ac.createGain();
  gain.gain.value = volume;
  src.connect(filter).connect(gain).connect(ac.destination);
  src.start();
}

function tone(frequency: number, start: number, duration: number, volume: number) {
  const ac = audio();
  if (!ac) return;
  const t = ac.currentTime + start;
  const osc = ac.createOscillator();
  osc.type = "sine";
  osc.frequency.value = frequency;
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(volume, t + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + duration);
  osc.connect(gain).connect(ac.destination);
  osc.start(t);
  osc.stop(t + duration + 0.05);
}

export const sounds = {
  key: () => tick(2600, 0.18),
  wrongKey: () => tick(900, 0.22),
  word: () => {
    if (!soundEnabled()) return;
    tone(1046.5, 0, 0.18, 0.05); // dó
    tone(1568, 0.06, 0.22, 0.04); // sol
  },
  sentence: (perfect: boolean) => {
    if (!soundEnabled()) return;
    const notes = perfect ? [523.25, 659.25, 783.99, 1046.5] : [523.25, 659.25, 783.99];
    notes.forEach((f, i) => tone(f, i * 0.08, 0.5, perfect ? 0.06 : 0.045));
  },
};
