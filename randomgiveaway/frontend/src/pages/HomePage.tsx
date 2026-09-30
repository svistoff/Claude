import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  createGiveaway,
  drawGiveaway,
  importParticipants,
  loadCommentsLive,
  previewParticipants,
  publishTelegram,
} from '../api/client'
import { defaultSettings, type Giveaway, type GiveawaySettings, type ParticipantsPreview, type Source } from '../api/types'
import { AdminTokenField } from '../components/AdminTokenField'
import { Switch } from '../components/Switch'

const SOURCES: { value: Source; label: string }[] = [
  { value: 'instagram', label: 'Instagram' },
  { value: 'vk', label: 'VK' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'import', label: 'Импорт файла' },
]

type Step = 'setup' | 'preview' | 'telegram-live'

export function HomePage() {
  const navigate = useNavigate()

  const [step, setStep] = useState<Step>('setup')
  const [source, setSource] = useState<Source>('instagram')
  const [postUrl, setPostUrl] = useState('')
  const [telegramText, setTelegramText] = useState('')
  const [telegramImage, setTelegramImage] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [importFormat, setImportFormat] = useState<'csv' | 'json' | 'list'>('csv')
  const [settings, setSettings] = useState<GiveawaySettings>(defaultSettings)
  const [excludedUsersText, setExcludedUsersText] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [giveawayId, setGiveawayId] = useState<number | null>(null)
  const [preview, setPreview] = useState<ParticipantsPreview | null>(null)
  const [telegramGiveaway, setTelegramGiveaway] = useState<Giveaway | null>(null)

  function updateSettings<K extends keyof GiveawaySettings>(key: K, value: GiveawaySettings[K]) {
    setSettings((s) => ({ ...s, [key]: value }))
  }

  // Telegram не отдаёт комментарии по ссылке (см. README, «Подключение
  // Telegram») — участники накапливаются по кнопке/рефералкам, поэтому
  // после публикации опрашиваем их число вместо одноразовой загрузки.
  useEffect(() => {
    if (step !== 'telegram-live' || !giveawayId) return
    let cancelled = false
    const poll = async () => {
      try {
        const p = await previewParticipants(giveawayId)
        if (!cancelled) setPreview(p)
      } catch {
        // временная сетевая ошибка при опросе — не прерываем поток, попробуем на следующем тике
      }
    }
    poll()
    const interval = setInterval(poll, 4000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [step, giveawayId])

  async function handleLoadComments() {
    setError(null)

    if (source === 'import') {
      if (!file) {
        setError('Выберите файл для импорта')
        return
      }
    } else if (source === 'telegram') {
      if (!telegramText.trim()) {
        setError('Введите текст поста')
        return
      }
    } else if (!postUrl.trim()) {
      setError('Укажите ссылку на пост')
      return
    }

    setLoading(true)
    try {
      const finalSettings: GiveawaySettings = {
        ...settings,
        excluded_users: excludedUsersText
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
      }

      const giveaway = await createGiveaway({
        source,
        post_url: source === 'import' ? postUrl.trim() || `import:${file!.name}` : postUrl.trim(),
        title: title.trim() || null,
        settings: finalSettings,
      })
      setGiveawayId(giveaway.id)

      if (source === 'telegram') {
        const published = await publishTelegram(giveaway.id, telegramText.trim(), telegramImage)
        setTelegramGiveaway(published)
        setStep('telegram-live')
        return
      }

      const result =
        source === 'import'
          ? await importParticipants(giveaway.id, file!, importFormat)
          : await loadCommentsLive(giveaway.id)

      setPreview(result)
      setStep('preview')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить комментарии. Проверьте соединение.')
    } finally {
      setLoading(false)
    }
  }

  async function handleDraw() {
    if (!giveawayId) return
    setError(null)
    setLoading(true)
    try {
      const result = await drawGiveaway(giveawayId)
      navigate(`/draw/${giveawayId}`, { state: result })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось провести розыгрыш.')
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <div className="page-inner">
        <div className="brand">Random.ЕКБ ГИД</div>

        {step === 'setup' && (
          <>
            <h1 className="title">Розыгрыш</h1>
            <p className="subtitle">Выберите площадку и вставьте ссылку на пост.</p>

            <AdminTokenField />

            {error && <div className="error-box">{error}</div>}

            <div className="source-grid">
              {SOURCES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  className="source-btn"
                  data-active={source === s.value}
                  onClick={() => setSource(s.value)}
                >
                  {s.label}
                </button>
              ))}
            </div>

            <div className="card">
              {source === 'import' ? (
                <>
                  <div className="field">
                    <label htmlFor="file">Файл участников (CSV / JSON / список usernames)</label>
                    <input
                      id="file"
                      type="file"
                      accept=".csv,.json,.txt"
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="format">Формат файла</label>
                    <select
                      id="format"
                      value={importFormat}
                      onChange={(e) => setImportFormat(e.target.value as typeof importFormat)}
                      style={{
                        width: '100%',
                        padding: '14px 16px',
                        borderRadius: 10,
                        border: '1px solid var(--border)',
                        background: 'var(--bg-elevated)',
                        color: 'var(--text)',
                        fontSize: '1rem',
                      }}
                    >
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                      <option value="list">Список usernames (по одному в строке)</option>
                    </select>
                  </div>
                </>
              ) : source === 'telegram' ? (
                <>
                  <div className="field">
                    <label htmlFor="telegram-text">Текст поста для канала</label>
                    <textarea
                      id="telegram-text"
                      rows={5}
                      value={telegramText}
                      onChange={(e) => setTelegramText(e.target.value)}
                      placeholder={'Например: Разыгрываем билеты на фестиваль!\nЖми «Участвую» и приглашай друзей — больше шансов на победу.'}
                    />
                    <p className="field-hint">
                      Бот сам опубликует этот текст в канал с кнопкой «Участвую» — ссылку на пост вставлять не нужно.
                    </p>
                  </div>
                  <div className="field">
                    <label htmlFor="telegram-image">Картинка к посту (необязательно)</label>
                    <input
                      id="telegram-image"
                      type="file"
                      accept="image/*"
                      onChange={(e) => setTelegramImage(e.target.files?.[0] ?? null)}
                    />
                    {telegramImage && (
                      <p className="field-hint">
                        {telegramImage.name} — с картинкой текст поста ограничен 1024 символами (подпись к фото).
                      </p>
                    )}
                  </div>
                </>
              ) : (
                <div className="field">
                  <label htmlFor="post-url">Ссылка на пост</label>
                  <input
                    id="post-url"
                    type="url"
                    value={postUrl}
                    onChange={(e) => setPostUrl(e.target.value)}
                    placeholder="https://www.instagram.com/p/..."
                  />
                </div>
              )}

              <div className="field">
                <label htmlFor="title">Название розыгрыша (необязательно)</label>
                <input
                  id="title"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Например: Билеты на фестиваль"
                />
              </div>
            </div>

            <div className="card">
              <div className="field" style={{ marginBottom: 8 }}>
                <label htmlFor="winners">Количество победителей</label>
                <input
                  id="winners"
                  type="number"
                  min={1}
                  value={settings.winners_count}
                  onChange={(e) => updateSettings('winners_count', Math.max(1, Number(e.target.value)))}
                />
              </div>
              <div className="field">
                <label htmlFor="backups">Количество запасных</label>
                <input
                  id="backups"
                  type="number"
                  min={0}
                  value={settings.backup_winners_count}
                  onChange={(e) => updateSettings('backup_winners_count', Math.max(0, Number(e.target.value)))}
                />
              </div>

              <Switch
                label="Один пользователь = один шанс"
                hint={
                  source === 'telegram'
                    ? 'Иначе за каждого приглашённого друга — дополнительный шанс'
                    : 'Иначе несколько комментариев одного человека увеличивают его шанс'
                }
                checked={settings.unique_user}
                onChange={(v) => updateSettings('unique_user', v)}
              />
              {source !== 'telegram' && (
                <>
                  <Switch
                    label="Учитывать ответы на комментарии"
                    checked={settings.include_replies}
                    onChange={(v) => updateSettings('include_replies', v)}
                  />
                  <Switch
                    label="Требовать упоминание пользователя (@)"
                    checked={settings.require_mention}
                    onChange={(v) => updateSettings('require_mention', v)}
                  />
                </>
              )}
              <Switch
                label="Исключить автора поста"
                checked={settings.exclude_post_author}
                onChange={(v) => updateSettings('exclude_post_author', v)}
              />

              {source !== 'telegram' && (
                <div className="field" style={{ marginTop: 16 }}>
                  <label htmlFor="required-text">Учитывать только комментарии, содержащие (необязательно)</label>
                  <input
                    id="required-text"
                    type="text"
                    value={settings.required_text ?? ''}
                    onChange={(e) => updateSettings('required_text', e.target.value || null)}
                    placeholder="например: @друг"
                  />
                </div>
              )}

              <div className="field">
                <label htmlFor="excluded">Исключить пользователей (по одному в строке)</label>
                <textarea
                  id="excluded"
                  rows={3}
                  value={excludedUsersText}
                  onChange={(e) => setExcludedUsersText(e.target.value)}
                  placeholder={'@user1\n@user2'}
                />
              </div>
            </div>

            <button className="btn btn-primary" onClick={handleLoadComments} disabled={loading}>
              {loading
                ? source === 'telegram'
                  ? 'Публикуем…'
                  : 'Загружаем…'
                : source === 'telegram'
                  ? 'Опубликовать в Telegram'
                  : 'Загрузить комментарии'}
            </button>
          </>
        )}

        {step === 'telegram-live' && telegramGiveaway && (
          <>
            <h1 className="title">Пост опубликован</h1>
            <p className="subtitle">
              Участники накапливаются по мере того, как люди жмут «Участвую» и приглашают друзей.
            </p>

            {error && <div className="error-box">{error}</div>}

            <div className="card">
              <div className="field" style={{ marginBottom: 0 }}>
                <a href={telegramGiveaway.post_url} target="_blank" rel="noreferrer">
                  Открыть пост в канале →
                </a>
              </div>
            </div>

            <div className="card">
              <div className="stat-row">
                <span className="stat-label">Участников сейчас</span>
                <span className="stat-value">{preview?.participants_after_rules ?? 0}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Победителей</span>
                <span className="stat-value">{settings.winners_count}</span>
              </div>
              {settings.backup_winners_count > 0 && (
                <div className="stat-row">
                  <span className="stat-label">Запасных</span>
                  <span className="stat-value">{settings.backup_winners_count}</span>
                </div>
              )}
              <p className="field-hint">Число обновляется само каждые несколько секунд.</p>
            </div>

            <button
              className="btn btn-primary"
              onClick={handleDraw}
              disabled={loading || (preview?.participants_after_rules ?? 0) < settings.winners_count}
            >
              {loading ? 'Запускаем…' : 'ПРОВЕСТИ РОЗЫГРЫШ'}
            </button>
            <div style={{ height: 12 }} />
            <button
              className="btn btn-ghost"
              onClick={() => {
                setStep('setup')
                setTelegramGiveaway(null)
                setTelegramImage(null)
                setPreview(null)
              }}
              disabled={loading}
            >
              Назад к настройкам
            </button>
          </>
        )}

        {step === 'preview' && preview && (
          <>
            <h1 className="title">Комментарии загружены</h1>

            {error && <div className="error-box">{error}</div>}

            <div className="card">
              <div className="stat-row">
                <span className="stat-label">Всего комментариев</span>
                <span className="stat-value">{preview.total_comments}</span>
              </div>
              {preview.unique_users !== null && (
                <div className="stat-row">
                  <span className="stat-label">Уникальных пользователей</span>
                  <span className="stat-value">{preview.unique_users}</span>
                </div>
              )}
              {preview.repeated_comments !== null && (
                <div className="stat-row">
                  <span className="stat-label">Повторных комментариев</span>
                  <span className="stat-value">{preview.repeated_comments}</span>
                </div>
              )}
            </div>

            <div className="card">
              <div className="stat-row">
                <span className="stat-label">В розыгрыше участвуют</span>
                <span className="stat-value">{preview.participants_before_rules}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">После применения правил</span>
                <span className="stat-value">{preview.participants_after_rules}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Платформа</span>
                <span className="stat-value">{SOURCES.find((s) => s.value === source)?.label}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Победителей</span>
                <span className="stat-value">{settings.winners_count}</span>
              </div>
              {settings.backup_winners_count > 0 && (
                <div className="stat-row">
                  <span className="stat-label">Запасных</span>
                  <span className="stat-value">{settings.backup_winners_count}</span>
                </div>
              )}
            </div>

            {preview.participants_after_rules === 0 ? (
              <div className="error-box">Не найдено участников, соответствующих заданным условиям.</div>
            ) : preview.participants_after_rules < settings.winners_count ? (
              <div className="error-box">
                Недостаточно участников: {preview.participants_after_rules} доступно, а победителей требуется{' '}
                {settings.winners_count}.
              </div>
            ) : null}

            <button
              className="btn btn-primary"
              onClick={handleDraw}
              disabled={loading || preview.participants_after_rules < settings.winners_count}
            >
              {loading ? 'Запускаем…' : 'ПРОВЕСТИ РОЗЫГРЫШ'}
            </button>
            <div style={{ height: 12 }} />
            <button className="btn btn-ghost" onClick={() => setStep('setup')} disabled={loading}>
              Назад к настройкам
            </button>
          </>
        )}
      </div>
    </div>
  )
}
