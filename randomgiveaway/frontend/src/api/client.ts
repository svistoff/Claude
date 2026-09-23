import type {
  DrawResult,
  Giveaway,
  GiveawaySettings,
  Participant,
  ParticipantsPreview,
  PublicResult,
  Source,
} from './types'

const ADMIN_TOKEN_KEY = 'rg_admin_token'

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) ?? ''
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = getAdminToken()
  if (token) headers.set('X-Admin-Token', token)

  const resp = await fetch(path, { ...init, headers })
  if (!resp.ok) {
    let detail = `Ошибка ${resp.status}`
    try {
      const body = await resp.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // тело не JSON — оставляем стандартное сообщение
    }
    throw new ApiError(resp.status, detail)
  }
  return resp.json() as Promise<T>
}

export interface CreateGiveawayInput {
  source: Source
  post_url: string
  title?: string | null
  post_author_user_id?: string | null
  settings: GiveawaySettings
}

export function createGiveaway(input: CreateGiveawayInput): Promise<Giveaway> {
  return request<Giveaway>('/api/giveaways', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function getGiveaway(id: number): Promise<Giveaway> {
  return request<Giveaway>(`/api/giveaways/${id}`)
}

export function importParticipants(
  id: number,
  file: File,
  format: 'csv' | 'json' | 'list',
): Promise<ParticipantsPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('format', format)
  return request<ParticipantsPreview>(`/api/giveaways/${id}/import`, {
    method: 'POST',
    body: form,
  })
}

export function loadCommentsLive(id: number): Promise<ParticipantsPreview> {
  return request<ParticipantsPreview>(`/api/giveaways/${id}/load-comments`, { method: 'POST' })
}

export function previewParticipants(id: number): Promise<ParticipantsPreview> {
  return request<ParticipantsPreview>(`/api/giveaways/${id}/participants/process`, { method: 'POST' })
}

export function listParticipants(id: number): Promise<Participant[]> {
  return request<Participant[]>(`/api/giveaways/${id}/participants`)
}

export function drawGiveaway(id: number): Promise<DrawResult> {
  return request<DrawResult>(`/api/giveaways/${id}/draw`, { method: 'POST' })
}

export function getResult(id: number): Promise<DrawResult> {
  return request<DrawResult>(`/api/giveaways/${id}/result`)
}

export function getPublicResult(publicId: string): Promise<PublicResult> {
  return request<PublicResult>(`/api/results/${publicId}`)
}
