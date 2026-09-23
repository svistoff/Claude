import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getPublicResult } from '../api/client'
import type { PublicResult, Winner } from '../api/types'

const SOURCE_LABELS: Record<string, string> = {
  instagram: 'Instagram',
  vk: 'VK',
  telegram: 'Telegram',
  import: 'Импорт',
}

const MEDALS = ['🥇', '🥈', '🥉']

function displayName(w: Winner): string {
  return w.username ? `@${w.username}` : (w.display_name ?? w.source_user_id)
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function PublicResultPage() {
  const { publicId } = useParams<{ publicId: string }>()
  const [result, setResult] = useState<PublicResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!publicId) return
    getPublicResult(publicId)
      .then(setResult)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить результат'))
  }, [publicId])

  if (error) {
    return (
      <div className="page">
        <div className="page-inner centered">
          <div className="error-box">{error}</div>
          <Link className="btn btn-secondary" to="/">
            На главную
          </Link>
        </div>
      </div>
    )
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
    <div className="page">
      <div className="page-inner">
        <div className="brand">Random.ЕКБ ГИД</div>
        <h1 className="title">Результат розыгрыша</h1>
        {result.title && <p className="subtitle">{result.title}</p>}

        <div className="card">
          <div className="stat-row">
            <span className="stat-label">Платформа</span>
            <span className="stat-value">{SOURCE_LABELS[result.source] ?? result.source}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Ссылка на пост</span>
            <span className="stat-value">
              <a href={result.post_url} target="_blank" rel="noreferrer">
                открыть
              </a>
            </span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Комментариев</span>
            <span className="stat-value">{result.comments_count}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Участников</span>
            <span className="stat-value">{result.participants_count}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Проведён</span>
            <span className="stat-value">{formatDate(result.drawn_at)}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">ID розыгрыша</span>
            <span className="stat-value">{result.public_id}</span>
          </div>
        </div>

        <div className="card">
          <h2 style={{ margin: '0 0 16px', fontSize: '1.1rem' }}>Победители</h2>
          <div className="final-list" style={{ maxWidth: 'none' }}>
            {result.winners.map((w) => (
              <div className="final-item" key={`w-${w.position}`}>
                <span className="final-position">{MEDALS[w.position - 1] ?? w.position}</span>
                <span className="final-name">{displayName(w)}</span>
              </div>
            ))}
          </div>

          {result.backups.length > 0 && (
            <>
              <h2 style={{ margin: '20px 0 12px', fontSize: '1rem', color: 'var(--text-dim)' }}>Запасные</h2>
              <div className="final-list" style={{ maxWidth: 'none' }}>
                {result.backups.map((w) => (
                  <div className="final-item" key={`b-${w.position}`}>
                    <span className="final-position">{w.position}</span>
                    <span className="final-name">{displayName(w)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {result.result_hash && (
          <div className="card" style={{ fontSize: '0.8rem', color: 'var(--text-dim)', wordBreak: 'break-all' }}>
            <div style={{ marginBottom: 6 }}>Хэш результата (подтверждение честности розыгрыша):</div>
            <code>{result.result_hash}</code>
          </div>
        )}

        <p className="subtitle" style={{ textAlign: 'center', marginTop: 12 }}>
          Розыгрыш проведён с помощью{' '}
          <a href="https://ekb-guide.ru" target="_blank" rel="noreferrer">
            ЕКБ ГИД
          </a>
        </p>
      </div>
    </div>
  )
}
