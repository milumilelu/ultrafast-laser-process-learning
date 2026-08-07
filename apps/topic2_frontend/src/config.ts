export const config = {
  acceptanceMode: import.meta.env.VITE_ACCEPTANCE_MODE === 'true',
  topic2ApiUrl: import.meta.env.VITE_TOPIC2_API_URL ?? '/api/v1',
  agentApiUrl: import.meta.env.VITE_AGENT_API_URL ?? '/agent-api',
}
