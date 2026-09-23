export type Source = 'instagram' | 'vk' | 'telegram' | 'import'

export interface GiveawaySettings {
  unique_user: boolean
  include_replies: boolean
  require_mention: boolean
  required_text: string | null
  exclude_post_author: boolean
  excluded_users: string[]
  winners_count: number
  backup_winners_count: number
}

export const defaultSettings: GiveawaySettings = {
  unique_user: true,
  include_replies: true,
  require_mention: false,
  required_text: null,
  exclude_post_author: true,
  excluded_users: [],
  winners_count: 1,
  backup_winners_count: 0,
}

export type GiveawayStatus = 'DRAFT' | 'COMMENTS_LOADED' | 'PARTICIPANTS_READY' | 'DRAWN' | 'ERROR'

export interface Giveaway {
  id: number
  public_id: string
  source: Source
  post_url: string
  title: string | null
  status: GiveawayStatus
  comments_count: number
  participants_count: number
  winners_count: number
  backup_winners_count: number
  algorithm_version: string | null
  participants_hash: string | null
  result_hash: string | null
  created_at: string
  drawn_at: string | null
  settings: GiveawaySettings
}

export interface ParticipantsPreview {
  total_comments: number
  unique_users: number | null
  repeated_comments: number | null
  participants_before_rules: number
  participants_after_rules: number
}

export interface Participant {
  source_user_id: string
  username: string | null
  display_name: string | null
  comment_count: number
}

export interface Winner {
  position: number
  source_user_id: string
  username: string | null
  display_name: string | null
  comment_count: number
}

export interface DrawResult {
  giveaway: Giveaway
  winners: Winner[]
  backups: Winner[]
}

export interface PublicResult {
  public_id: string
  title: string | null
  source: Source
  post_url: string
  created_at: string
  drawn_at: string | null
  comments_count: number
  participants_count: number
  winners_count: number
  backup_winners_count: number
  algorithm_version: string | null
  participants_hash: string | null
  result_hash: string | null
  winners: Winner[]
  backups: Winner[]
}
