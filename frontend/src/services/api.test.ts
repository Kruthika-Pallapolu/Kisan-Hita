import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest, localizedApiError, sendVoiceAudio } from './api';
import { supportedLocales, translate } from '../localization';

afterEach(() => vi.unstubAllGlobals());

describe('API client', () => {
  it('returns typed JSON and sets content type for JSON requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ accepted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiRequest<{ accepted: boolean }>('/example', { method: 'POST', body: '{}' })).resolves.toEqual({ accepted: true });
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/v1/example');
    expect(fetchMock.mock.calls[0][1].headers['Content-Type']).toBe('application/json');
  });

  it('shows a useful message when the backend is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await expect(apiRequest('/example')).rejects.toThrow('Could not reach Kisan Hita');
  });

  it('sends recorded audio as WAV rather than labeling the Blob as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ accepted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await sendVoiceAudio('conversation-id', new Blob(['wav bytes'], { type: 'audio/wav' }));
    expect(fetchMock.mock.calls[0][1].headers['Content-Type']).toBe('audio/wav');
    expect(fetchMock.mock.calls[0][1].body).toBeInstanceOf(Blob);
  });

  it('preserves structured HTTP status and localizes common API failures', async () => {
    const statuses = [400, 401, 403, 404, 413, 415, 422, 429, 500];
    for (const status of statuses) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ error: { code: 'http_error', message: 'backend detail' } }) }));
      let caught: unknown;
      try { await apiRequest('/crop-health/analyze'); } catch (error) { caught = error; }
      expect(localizedApiError(caught, 'te', '/crop-health/analyze')).not.toMatch(/connect|connection/i);
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ error: { code: 'http_error', message: 'This file doesn’t look like a PNG image.' } }) }));
    let invalidImage: unknown;
    try { await apiRequest('/crop-health/analyze'); } catch (error) { invalidImage = error; }
    expect(localizedApiError(invalidImage, 'te', '/crop-health/analyze')).toContain('ఫైల్');
  });

  it('maps crop-photo validation details to accurate selected-language messages', async () => {
    const cases = [
      { status: 422, message: 'This file doesn’t look like a PNG image.', expected: 'imageInvalid' as const },
      { status: 422, message: 'Choose a crop photo first.', expected: 'photoUnavailable' as const },
      { status: 415, message: 'Choose a JPG, PNG or WebP image.', expected: 'imageUnsupported' as const },
      { status: 413, message: 'This image is too large. Choose a smaller image.', expected: 'imageTooLarge' as const },
      { status: 503, message: 'Crop image diagnosis is unavailable.', expected: 'diagnosisUnavailable' as const },
      { status: 500, message: 'Something went wrong. Please try again.', expected: 'imageProcessingFailed' as const },
    ];
    for (const language of supportedLocales) {
      for (const item of cases) {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
          ok: false, status: item.status,
          json: async () => ({ error: { code: 'http_error', message: item.message } }),
        }));
        let caught: unknown;
        try { await apiRequest('/crop-health/analyze'); } catch (error) { caught = error; }
        expect(localizedApiError(caught, language, '/crop-health/analyze')).toBe(translate(language, item.expected));
        expect(localizedApiError(caught, language, '/crop-health/analyze')).not.toMatch(/connect|connection/i);
      }
    }
  });

  it('uses structured validation fields to distinguish a missing image from other 422 errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({
      error: { code: 'validation_error', message: 'Please check the information and try again.', details: [{ field: 'query.filename', message: 'Field required' }] },
    }) }));
    let caught: unknown;
    try { await apiRequest('/crop-health/analyze'); } catch (error) { caught = error; }
    expect(localizedApiError(caught, 'mr', '/crop-health/analyze')).toBe(translate('mr', 'photoUnavailable'));
  });
});
