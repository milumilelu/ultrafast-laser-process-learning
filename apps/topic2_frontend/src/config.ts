/** 构建期注入的版本标识（vite define）；页面 Header 展示，便于确认前端是否为最新构建。 */
declare const __BUILD_TIME__: string
declare const __FRONTEND_VERSION__: string

export const APP_VERSION = __FRONTEND_VERSION__
export const APP_BUILD_TIME = __BUILD_TIME__

export const config = {
  acceptanceMode: import.meta.env.VITE_ACCEPTANCE_MODE === 'true',
  topic2ApiUrl: import.meta.env.VITE_TOPIC2_API_URL ?? '/api/v1',
  agentApiUrl: import.meta.env.VITE_AGENT_API_URL ?? '/agent-api',
}
