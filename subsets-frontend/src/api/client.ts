import createFetchClient, { type Middleware } from 'openapi-fetch'
import createReactQueryClient from 'openapi-react-query'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type UserResponse = Schemas['UserResponse']
export type TokenResponse = Schemas['TokenResponse']
export type FeedMessageResponse = Schemas['FeedMessageResponse']
export type FeedReplyResponse = Schemas['FeedReplyResponse']
export type MessageResponse = Schemas['MessageResponse']

export type WebSocketServerMessage = {
  type: 'message'
  message: FeedMessageResponse
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const TOKEN_STORAGE_KEY = 'subsets-chat:token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setStoredToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  } else {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  }
}

const UNAUTHORIZED_EVENT = 'subsets-chat:unauthorized'

export function onUnauthorized(handler: () => void): () => void {
  const listener = () => handler()
  window.addEventListener(UNAUTHORIZED_EVENT, listener)
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, listener)
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getStoredToken()
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`)
    }
    return request
  },
  async onResponse({ response }) {
    if (response.status === 401) {
      setStoredToken(null)
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    }
    return response
  },
}

export const fetchClient = createFetchClient<paths>({ baseUrl: API_BASE_URL })
fetchClient.use(authMiddleware)

export const $api = createReactQueryClient(fetchClient)

export function buildWebSocketUrl(): string {
  const url = new URL(API_BASE_URL)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/ws'
  return url.toString()
}
