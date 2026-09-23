import { useState } from 'react'
import { getAdminToken, setAdminToken } from '../api/client'

export function AdminTokenField() {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(getAdminToken())

  return (
    <div style={{ marginBottom: 20 }}>
      <button
        type="button"
        className="btn btn-ghost"
        style={{ width: 'auto', padding: '6px 0', fontSize: '0.85rem' }}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? 'Скрыть' : 'Токен доступа'} {value ? '✓' : ''}
      </button>
      {open && (
        <div className="field" style={{ marginTop: 8 }}>
          <label htmlFor="admin-token">X-Admin-Token (см. .env на сервере)</label>
          <input
            id="admin-token"
            type="text"
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              setAdminToken(e.target.value)
            }}
            placeholder="оставь пустым, если ADMIN_TOKEN не задан"
          />
        </div>
      )}
    </div>
  )
}
