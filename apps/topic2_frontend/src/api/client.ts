/** Minimal JSON fetch wrapper shared by all API adapters.
 *
 * 职责划分：`request()` 只接受相对路径（以 `/` 开头），并解析到 baseUrl；
 * `buildUrl()` 只负责拼接相对路径与查询参数。绝对 URL 不允许传入
 * `request()` —— 防止重复拼接前缀（如 /api/v1/api/v1/...）。
 */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export interface RequestOptions {
  timeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 60_000

export function resolveUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  if (/^https?:\/\//.test(path)) {
    throw new ApiError(0, `request() 不接受绝对 URL：${path}（请传相对路径）`)
  }
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export async function request<T>(
  baseUrl: string,
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  // 防护：GET/HEAD 请求携带 body 是浏览器非法请求（参数错位常见根源），
  // 立即抛出明确错误而不是让 fetch 静默失败。
  const upperMethod = method.toUpperCase()
  if ((upperMethod === 'GET' || upperMethod === 'HEAD') && body !== undefined) {
    throw new ApiError(
      0,
      `request() 非法调用：${upperMethod} ${path} 携带了 body（请把 options 作为第 5 个参数传入）`,
    )
  }
  const controller = new AbortController()
  const timer = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  )
  try {
    const response = await fetch(resolveUrl(baseUrl, path), {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`
      const text = await response.text().catch(() => '')
      if (text) detail = text.slice(0, 400)
      throw new ApiError(response.status, detail)
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, '请求超时')
    }
    throw new ApiError(0, error instanceof Error ? error.message : '网络错误')
  } finally {
    clearTimeout(timer)
  }
}

/** 只拼接相对路径与查询参数；返回值同样是相对路径（以 / 开头）。 */
export function buildUrl(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&')
  return query ? `${path}?${query}` : path
}
