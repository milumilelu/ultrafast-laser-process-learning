/** 旧路由兼容映射（任务说明 §3.2）：/identification → /application?tab=identification 等。 */

export const LEGACY_ROUTE_REDIRECTS: Record<string, string> = {
  '/identification': '/application?tab=identification',
  '/modeling': '/application?tab=modeling',
  '/optimization': '/application?tab=optimization',
  '/database': '/resources/data',
}

/** 精确路径匹配旧路由；无匹配返回 null。 */
export function legacyRouteRedirect(path: string): string | null {
  return LEGACY_ROUTE_REDIRECTS[path] ?? null
}
