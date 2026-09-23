// Простой синтезированный звук через Web Audio API — без внешних аудиофайлов.
// §22 ТЗ просит звуковые эффекты как опцию с возможностью отключения, не
// конкретный саунд-дизайн.

let ctx: AudioContext | null = null

function getContext(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  return ctx
}

function tone(freq: number, startAt: number, duration: number, gain: number) {
  const audioCtx = getContext()
  const osc = audioCtx.createOscillator()
  const gainNode = audioCtx.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  gainNode.gain.setValueAtTime(0, startAt)
  gainNode.gain.linearRampToValueAtTime(gain, startAt + 0.02)
  gainNode.gain.exponentialRampToValueAtTime(0.001, startAt + duration)
  osc.connect(gainNode)
  gainNode.connect(audioCtx.destination)
  osc.start(startAt)
  osc.stop(startAt + duration)
}

export function playTick() {
  const audioCtx = getContext()
  tone(660, audioCtx.currentTime, 0.05, 0.05)
}

export function playReveal() {
  const audioCtx = getContext()
  const now = audioCtx.currentTime
  tone(523.25, now, 0.18, 0.08)
  tone(659.25, now + 0.08, 0.22, 0.08)
  tone(783.99, now + 0.16, 0.35, 0.09)
}
