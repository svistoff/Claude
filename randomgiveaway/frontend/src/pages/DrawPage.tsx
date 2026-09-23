import confetti from 'canvas-confetti'
import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { getResult, listParticipants } from '../api/client'
import type { DrawResult, Winner } from '../api/types'
import { playReveal, playTick } from '../lib/sound'

type Phase = 'intro' | 'cycling' | 'reveal' | 'final'

const ORDINALS = [
  'ПЕРВЫЙ',
  'ВТОРОЙ',
  'ТРЕТИЙ',
  'ЧЕТВЁРТЫЙ',
  'ПЯТЫЙ',
  'ШЕСТОЙ',
  'СЕДЬМОЙ',
  'ВОСЬМОЙ',
  'ДЕВЯТЫЙ',
  'ДЕСЯТЫЙ',
]

function ordinal(n: number): string {
  return ORDINALS[n - 1] ?? `${n}-Й`
}

function displayName(w: Winner): string {
  return w.username ? `@${w.username}` : (w.display_name ?? w.source_user_id)
}

function fireConfetti() {
  const end = Date.now() + 1500
  const colors = ['#7c5cff', '#34d399', '#f5f5f7']
  ;(function frame() {
    confetti({ particleCount: 3, angle: 60, spread: 55, origin: { x: 0, y: 0.7 }, colors })
    confetti({ particleCount: 3, angle: 120, spread: 55, origin: { x: 1, y: 0.7 }, colors })
    if (Date.now() < end) requestAnimationFrame(frame)
  })()
  confetti({ particleCount: 140, spread: 100, origin: { y: 0.5 }, colors, startVelocity: 45 })
}

export function DrawPage() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const giveawayId = Number(id)

  const [result, setResult] = useState<DrawResult | null>((location.state as DrawResult) ?? null)
  const [candidateNames, setCandidateNames] = useState<string[]>([])
  const [phase, setPhase] = useState<Phase>('intro')
  const [queueIndex, setQueueIndex] = useState(0)
  const [cyclingName, setCyclingName] = useState('')
  const [soundOn, setSoundOn] = useState(true)
  const [effectsOn, setEffectsOn] = useState(true)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!result && giveawayId) {
      getResult(giveawayId)
        .then(setResult)
        .catch(() => navigate('/'))
    }
  }, [result, giveawayId, navigate])

  useEffect(() => {
    if (!giveawayId) return
    listParticipants(giveawayId)
      .then((ps) => setCandidateNames(ps.map((p) => (p.username ? `@${p.username}` : p.source_user_id))))
      .catch(() => {})
  }, [giveawayId])

  useEffect(() => {
    function onFsChange() {
      setIsFullscreen(Boolean(document.fullscreenElement))
    }
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  const sequence = useMemo(() => {
    if (!result) return []
    return [
      ...result.winners.map((w) => ({ ...w, isBackup: false as const })),
      ...result.backups.map((w) => ({ ...w, isBackup: true as const })),
    ]
  }, [result])

  const current = sequence[queueIndex]

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {})
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }

  function positionLabel(index: number): string {
    if (!result) return ''
    const item = sequence[index]
    if (item?.isBackup) return `ЗАПАСНОЙ ${index - result.winners.length + 1}`
    return sequence.length > 1 ? `${ordinal(index + 1)} ПОБЕДИТЕЛЬ` : 'ПОБЕДИТЕЛЬ'
  }

  function startCurrentReveal() {
    if (!current) return
    setPhase('cycling')
    const finalName = displayName(current)
    const candidates = candidateNames.length > 0 ? candidateNames : sequence.map(displayName)
    let tick = 0
    const totalTicks = 34

    function step() {
      tick += 1
      if (tick >= totalTicks) {
        setCyclingName(finalName)
        setPhase('reveal')
        if (soundOn) playReveal()
        if (effectsOn) fireConfetti()
        return
      }
      const progress = tick / totalTicks
      const delay = 45 + progress ** 2.4 * 480
      setCyclingName(candidates[Math.floor(Math.random() * candidates.length)] ?? finalName)
      if (soundOn) playTick()
      window.setTimeout(step, delay)
    }
    window.setTimeout(step, 60)
  }

  function nextAfterReveal() {
    if (queueIndex + 1 < sequence.length) {
      const next = queueIndex + 1
      setQueueIndex(next)
      setPhase('intro')
      window.setTimeout(startCurrentReveal, 1100)
    } else {
      setPhase('final')
    }
  }

  const publicUrl = result ? `${window.location.origin}/result/${result.giveaway.public_id}` : ''

  async function handleShare() {
    if (!publicUrl) return
    try {
      await navigator.clipboard.writeText(publicUrl)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      window.prompt('Скопируйте ссылку:', publicUrl)
    }
  }

  if (!result) {
    return (
      <div className="page">
        <div className="centered">
          <div className="spinner" />
        </div>
      </div>
    )
  }

  return (
    <div className="draw-screen">
      <div className="draw-toolbar">
        <button className="draw-toolbar-btn" onClick={toggleFullscreen}>
          {isFullscreen ? 'Выйти из полноэкранного' : 'ПОЛНОЭКРАННЫЙ РЕЖИМ'}
        </button>
        <button className="draw-toolbar-btn" onClick={() => setEffectsOn((v) => !v)}>
          Эффекты: {effectsOn ? 'вкл' : 'выкл'}
        </button>
        <button className="draw-toolbar-btn" onClick={() => setSoundOn((v) => !v)}>
          Звук: {soundOn ? 'вкл' : 'выкл'}
        </button>
      </div>

      <AnimatePresence mode="wait">
        {phase === 'intro' && queueIndex === 0 && (
          <motion.div
            key="intro"
            className="draw-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="draw-eyebrow">РОЗЫГРЫШ</div>
            <div className="draw-brand">ЕКБ ГИД</div>
            <div className="draw-count">{result.giveaway.participants_count} участников</div>
            <button className="btn btn-primary draw-start-btn" onClick={startCurrentReveal}>
              НАЧАТЬ
            </button>
          </motion.div>
        )}

        {phase === 'intro' && queueIndex > 0 && (
          <motion.div
            key={`next-${queueIndex}`}
            className="draw-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="draw-eyebrow">{positionLabel(queueIndex)}</div>
          </motion.div>
        )}

        {phase === 'cycling' && (
          <motion.div
            key="cycling"
            className="draw-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="draw-eyebrow">ВЫБИРАЕМ ПОБЕДИТЕЛЯ...</div>
            <div className="draw-cycling-name">{cyclingName}</div>
          </motion.div>
        )}

        {phase === 'reveal' && current && (
          <motion.div
            key="reveal"
            className="draw-center"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ type: 'spring', stiffness: 200, damping: 14 }}
          >
            <div className="draw-eyebrow">{current.isBackup ? positionLabel(queueIndex) : '🎉 ' + positionLabel(queueIndex)}</div>
            <motion.div
              className="draw-winner-name"
              initial={{ scale: 0.6 }}
              animate={{ scale: [0.6, 1.15, 1] }}
              transition={{ duration: 0.6 }}
            >
              {displayName(current)}
            </motion.div>
            <button className="btn btn-secondary draw-next-btn" onClick={nextAfterReveal}>
              {queueIndex + 1 < sequence.length ? 'Далее' : 'Показать итоги'}
            </button>
          </motion.div>
        )}

        {phase === 'final' && (
          <motion.div key="final" className="draw-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div className="draw-eyebrow">🎉 ПОБЕДИТЕЛИ 🎉</div>
            <div className="final-list">
              {result.winners.map((w) => (
                <div className="final-item" key={`w-${w.position}`}>
                  <span className="final-position">{w.position}</span>
                  <span className="final-name">{displayName(w)}</span>
                </div>
              ))}
            </div>
            {result.backups.length > 0 && (
              <>
                <div className="draw-eyebrow" style={{ marginTop: 24, fontSize: '1rem' }}>
                  Запасные
                </div>
                <div className="final-list">
                  {result.backups.map((w) => (
                    <div className="final-item" key={`b-${w.position}`}>
                      <span className="final-position">{w.position}</span>
                      <span className="final-name">{displayName(w)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            <div className="draw-count" style={{ marginTop: 24 }}>
              Участников: {result.giveaway.participants_count}
            </div>

            <button className="btn btn-primary" onClick={handleShare} style={{ marginTop: 24 }}>
              {copied ? 'Ссылка скопирована ✓' : 'Поделиться результатом'}
            </button>
            <div style={{ height: 12 }} />
            <button className="btn btn-secondary" onClick={() => navigate('/')}>
              Провести новый розыгрыш
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
