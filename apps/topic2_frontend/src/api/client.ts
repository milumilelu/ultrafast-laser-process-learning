/** Thin HTTP client. Only transport + error normalization; no science. */

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function normalizeMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (typeof detail === 'object' && detail !== null && 'detail' in detail) {
    return normalizeMessage((detail as { detail: unknown }).detail, fallback)
  }
  return fallback
}

export function buildQuery(params: Record<string, string | number | boolean | null | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string | number | boolean] =>
      entry[1] !== undefined && entry[1] !== null && entry[1] !== '',
  )
  if (entries.length === 0) return ''
  const query = new URLSearchParams()
  for (const [key, value] of entries) query.set(key, String(value))
  return `?${query.toString()}`
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function request<T>(
  baseUrl: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = path.startsWith('http')
    ? path
    : `${baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (cause) {
    throw new ApiError(0, `网络请求失败: ${(cause as Error).message}`, cause)
  }
  const body = await parseBody(response)
  if (!response.ok) {
    throw new ApiError(response.status, normalizeMessage(body, `HTTP ${response.status}`), body)
  }
  return body as T
}

/** POST/PUT/PATCH/DELETE with JSON body. */
export function jsonBody(payload: unknown): { body: string } {
  return { body: JSON.stringify(payload) }
}
