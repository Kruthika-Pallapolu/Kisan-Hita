import type { ChatResponse, CropHealthResponse, CropRequest, CropResponse, FarmTodayRequest, FarmTodayResponse, HealthResponse, MarketLookupResponse, MarketPriceRequest, VoiceCapabilities, VoiceConversation, VoiceTurn } from '../types/api';
import type { AudioInputResponse } from '../types/api';
import { translate } from '../localization';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');

export class ApiRequestError extends Error {
  constructor(message: string, readonly status: number | null, readonly code: string, readonly endpoint: string,
              readonly details: ReadonlyArray<{ field?: string; message?: string }> = []) {
    super(message);
    this.name = 'ApiRequestError';
  }
}

export function localizedApiError(error: unknown, language: string, endpoint = ''): string {
  if (!(error instanceof ApiRequestError)) return translate(language, 'requestFailed');
  if (error.status === null) return translate(language, 'offline');
  switch (error.status) {
    case 400: return translate(language, 'badRequest');
    case 401: return translate(language, 'unauthorized');
    case 403: return translate(language, 'forbidden');
    case 404: return translate(language, 'notFound');
    case 413: return translate(language, 'imageTooLarge');
    case 415: return translate(language, 'imageUnsupported');
    case 422:
      if (endpoint.includes('/crop-health/')) {
        const details = error instanceof ApiRequestError ? error.details : [];
        const detailText = [error.message, ...details.map((detail) => `${detail.field ?? ''} ${detail.message ?? ''}`)]
          .join(' ').toLowerCase();
        if (/choose (a )?crop photo first|missing (a )?crop photo|filename.+required/.test(detailText)) {
          return translate(language, 'photoUnavailable');
        }
        if (/too large|exceeds? the configured upload limit/.test(detailText)) return translate(language, 'imageTooLarge');
        if (/jpg, png or webp|unsupported|content.type|image format/.test(detailText)) return translate(language, 'imageUnsupported');
        if (/doesn.t look like|does not match|not a valid (png|jpe?g|webp)|image signature/.test(detailText)) {
          return translate(language, 'imageInvalid');
        }
        return translate(language, 'imageValidation');
      }
      return translate(language, 'validationError');
    case 429: return translate(language, 'tooManyRequests');
    case 503: return endpoint.includes('/crop-health/')
      ? translate(language, 'diagnosisUnavailable') : translate(language, 'serviceUnavailable');
    default: return error.status === 500 && endpoint.includes('/crop-health/')
      ? translate(language, 'imageProcessingFailed')
      : error.status >= 500 ? translate(language, 'requestFailed') : error.message;
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers: { Accept: 'application/json', ...(typeof init.body === 'string' ? { 'Content-Type': 'application/json' } : {}), ...init.headers } });
  } catch {
    throw new ApiRequestError('Could not reach Kisan Hita. Check that the backend is running and try again.', null, 'network_error', path);
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const envelope = payload && typeof payload === 'object' && 'error' in payload ? (payload as { error?: unknown }).error : null;
    const bodyError = envelope && typeof envelope === 'object' ? envelope as { message?: unknown; code?: unknown } : null;
    const message = typeof bodyError?.message === 'string' ? bodyError.message : `Request failed (${response.status}). Please try again.`;
    const code = typeof bodyError?.code === 'string' ? bodyError.code : 'http_error';
    const rawDetails = bodyError && 'details' in bodyError ? bodyError.details : null;
    const details = Array.isArray(rawDetails) ? rawDetails.flatMap((entry) => {
      if (!entry || typeof entry !== 'object') return [];
      const item = entry as { field?: unknown; message?: unknown };
      return [{
        ...(typeof item.field === 'string' ? { field: item.field } : {}),
        ...(typeof item.message === 'string' ? { message: item.message } : {}),
      }];
    }) : [];
    throw new ApiRequestError(message, response.status, code, path, details);
  }
  return response.json() as Promise<T>;
}

export const getHealth = () => apiRequest<HealthResponse>('/health');
export const getVoiceCapabilities = () => apiRequest<VoiceCapabilities>('/voice/capabilities');
export const createVoiceConversation = (language: string) => apiRequest<VoiceConversation>('/voice/conversations', { method: 'POST', body: JSON.stringify({ language }) });
export const sendVoiceMessage = (conversationId: string, message: string, signal?: AbortSignal, clientTurnId?: string, toolArguments?: Record<string, unknown>) => apiRequest<VoiceTurn>(`/voice/conversations/${encodeURIComponent(conversationId)}/messages`, { method: 'POST', body: JSON.stringify({ message, client_turn_id: clientTurnId ?? (globalThis.crypto?.randomUUID?.() ?? `turn-${Date.now()}-${Math.random().toString(36).slice(2)}`), tool_arguments: toolArguments ?? {} }), signal });
export const saveFarmLocation = (conversationId: string, location: { state: string; district: string }) => apiRequest<VoiceConversation>(`/voice/conversations/${encodeURIComponent(conversationId)}/farm-location`, { method: 'PUT', body: JSON.stringify(location) });
export const setConversationLanguage = (conversationId: string, language: string) => apiRequest<VoiceConversation>(`/voice/conversations/${encodeURIComponent(conversationId)}/language`, { method: 'PUT', body: JSON.stringify({ language }) });
export const sendVoiceAudio = (conversationId: string, audio: Blob) => apiRequest<AudioInputResponse>(`/voice/conversations/${encodeURIComponent(conversationId)}/audio`, { method: 'POST', body: audio, headers: { 'Content-Type': 'audio/wav' } });
export const synthesizeVoice = (conversationId: string, message: string) => apiRequest<{ available: boolean; audio_base64: string; is_mock: boolean }>(`/voice/conversations/${encodeURIComponent(conversationId)}/speech`, { method: 'POST', body: JSON.stringify({ message }) });
export const getFarmToday = (request: FarmTodayRequest, signal?: AbortSignal) => apiRequest<FarmTodayResponse>('/farm/today', { method: 'POST', body: JSON.stringify(request), signal });
export const getCropRecommendations = (request: CropRequest) => apiRequest<CropResponse>('/crops/recommendations', { method: 'POST', body: JSON.stringify(request) });
export const getMarketPrices = (request: MarketPriceRequest) => apiRequest<MarketLookupResponse>('/market/prices', { method: 'POST', body: JSON.stringify(request) });
export const askAssistant = (request: { conversation_id?: string; language: string; message: string; context?: Record<string, unknown> }) => apiRequest<ChatResponse>('/assistant/messages', { method: 'POST', body: JSON.stringify(request) });
export function sendCropPhoto(file: File, fields: { crop?: string; symptoms?: string; language: string; conversationId?: string }) {
  const query = new URLSearchParams({ filename: file.name, language: fields.language });
  if (fields.crop) query.set('crop', fields.crop);
  if (fields.symptoms) query.set('symptoms', fields.symptoms);
  if (fields.conversationId) query.set('conversation_id', fields.conversationId);
  return apiRequest<CropHealthResponse>(`/crop-health/analyze?${query}`, { method: 'POST', body: file, headers: { 'Content-Type': file.type } });
}
