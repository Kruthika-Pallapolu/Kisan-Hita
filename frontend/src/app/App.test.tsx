import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';
import { messages, supportedLocales, translate } from '../localization';

function routeFetch(intent: string, destination: string) {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: true, prisma_input_enabled: true, timbre_output_enabled: true }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'voice-1', language: 'en-IN', language_status: 'unverified', language_notice: 'notice' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'voice-1', language: 'en-IN', feature_implemented: false, feature_notice: 'No live result is available.', result: { intent, destination, entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.82, clarification_required: false, response: 'No live result is available.', language: 'en-IN', response_language: 'en-IN', is_mock: true, source: 'test mock' } }) });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); window.history.replaceState({}, '', '/'); });

describe('feature app foundation', () => {
  it('shows routes for all five feature areas', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: { weather: 'mock' } }) }));
    render(<App />);
    expect(await screen.findByText('Ready to help.')).toBeInTheDocument();
    for (const label of ['Weather', 'Choose My Crop', 'Check My Crop', 'Market Prices', 'Ask Kisan Hita']) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  });

  it('keeps typing available and does not expose a microphone when Prisma is disabled', async () => {
    vi.stubGlobal('SpeechRecognition', vi.fn(() => { throw new Error('Browser STT must not be used'); }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: false, prisma_input_enabled: false, timbre_output_enabled: false }) }));
    render(<App />);
    expect(await screen.findByText(/Prisma voice input is not enabled on the server/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start listening' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Or type a request')).toBeInTheDocument();
    expect(document.querySelector('.assistant-dock .dock-mic')).not.toBeInTheDocument();
  });

  it('routes a weather sample into the farm location workflow', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'c1', language: 'en-IN', language_status: 'unverified', language_notice: 'unverified' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'c1', language: 'en-IN', feature_implemented: false, feature_notice: 'This feature page is a Stage 2 integration placeholder. No agricultural result was generated.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.82, clarification_required: false, response: 'I understood the request category. This feature does not have live farming results yet.', language: 'en-IN', is_mock: true, source: 'local rules' } }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Will it rain tomorrow?' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(screen.getByText(/Choose the state and district or town/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('mock-tests recorded audio through transcript correction, orchestrator routing and TTS', async () => {
    localStorage.clear();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) } });
    class FakeRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive'; mimeType = 'audio/webm'; ondataavailable: ((event: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['fixture'], { type: this.mimeType }) }); this.onstop?.(); }
    }
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    const audioPlay = vi.fn(async () => {});
    class FakeAudio { onended: (() => void) | null = null; play = audioPlay; pause = vi.fn(); }
    vi.stubGlobal('Audio', FakeAudio);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:answer-audio') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: class {
      async decodeAudioData() { return { duration: 0.05, sampleRate: 16000, numberOfChannels: 1, getChannelData: () => new Float32Array(800) }; }
      async close() {}
    } });
    const turn = { conversation_id: 'voice-e2e', language: 'en', feature_implemented: true, feature_notice: 'Weather result from fixture.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.9, clarification_required: false, response: 'Rain is expected tomorrow.', language: 'en', response_language: 'en', is_mock: false, source: 'local test fixture', tool_name: 'my-farm-today', tool_result: { forecast_data: { location: 'Warangal', state: 'Telangana', district: 'Warangal', observed_at: null, forecast: [], advice: [], alerts: [], source: 'weather test fixture', is_mock: false, notice: 'fixture', current: null, fetched_at: null, warnings_available: false } } } };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: true, prisma_input_enabled: true, timbre_output_enabled: true }) } as Response;
      if (url.endsWith('/voice/conversations') && init?.method === 'POST') return { ok: true, json: async () => ({ conversation_id: 'voice-e2e', language: 'en', language_status: 'supported', language_notice: '' }) } as Response;
      if (url.endsWith('/audio')) return { ok: true, json: async () => ({ accepted: true, transcribed: true, text: 'Will rain tomorrow?', language: 'en-IN', is_mock: false, notice: 'test fixture' }) } as Response;
      if (url.endsWith('/messages')) return { ok: true, json: async () => turn } as Response;
      if (url.endsWith('/speech')) return { ok: true, json: async () => ({ available: true, audio_base64: 'UklGRg==', is_mock: false }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Start listening' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Finish speaking' }));
    const question = await screen.findByLabelText('Or type a request') as HTMLInputElement;
    await waitFor(() => expect(question.value).toBe('Will rain tomorrow?'));
    expect(requests.some((request) => request.url.endsWith('/messages'))).toBe(false);
    fireEvent.change(question, { target: { value: 'Will it rain tomorrow in Warangal?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/speech'))).toBe(true));
    const audioRequest = requests.find((request) => request.url.endsWith('/audio'))!;
    expect(audioRequest.init?.headers).toMatchObject({ 'Content-Type': 'audio/wav' });
    const messageRequest = requests.find((request) => request.url.endsWith('/messages'))!;
    expect(JSON.parse(String(messageRequest.init?.body)).message).toBe('Will it rain tomorrow in Warangal?');
    expect(screen.getAllByText('Rain is expected tomorrow.')).toHaveLength(2);
    expect(audioPlay).toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: 'Stop speaking' }));
    fireEvent.click(screen.getByRole('button', { name: 'Play answer' }));
    await waitFor(() => expect(audioPlay).toHaveBeenCalledTimes(2));
  });

  it('does not request browser location permission automatically', async () => {
    const getCurrentPosition = vi.fn((_success: PositionCallback, onError: PositionErrorCallback) => onError({ code: 1 } as GeolocationPositionError));
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) }));
    window.history.replaceState({}, '', '/my-farm-today');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(getCurrentPosition).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use current location' }));
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('status')).toHaveTextContent(/Enter your farm’s state/i);
  });

  it('uses explicitly requested GPS coordinates with the manually selected farm for weather', async () => {
    const forecast = { location: 'Warangal, Hanamkonda, Telangana, India', state: 'Telangana', district: 'Warangal', resolved_place: 'Warangal, Hanamkonda, Telangana, India', geographic_resolution: 'Open-Meteo grid point near the selected place', observed_at: null, current: { time: '2026-11-03T12:00:00', temperature_c: 28, relative_humidity_percent: 60, precipitation_mm: 0, wind_speed_kmh: 7 }, forecast: [{ date: '2026-11-03', summary: 'Clear', temperature_c: 30, temperature_min_c: 20, precipitation_mm: 0, precipitation_probability: 5 }], advice: ['Check conditions locally.'], alerts: [], warnings_available: false, warnings_notice: 'Official warnings unavailable.', source: 'Open-Meteo forecast model', is_mock: false, notice: 'Forecast estimate.', fetched_at: '2026-11-03T12:00:00Z', forecast_period: '2026-11-03 to 2026-11-03' };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      const payload = url.includes('/farm/today') ? forecast : url.includes('/farm-location')
        ? { conversation_id: 'voice-1', language: 'en-IN', language_status: 'unverified', language_notice: 'notice', farm_location: { state: 'Telangana', district: 'Warangal' } }
        : url.includes('/conversations') ? { conversation_id: 'voice-1', language: 'en-IN', language_status: 'unverified', language_notice: 'notice' }
          : { status: 'ok', environment: 'test', providers: {} };
      return { ok: true, json: async () => payload } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    const getCurrentPosition = vi.fn((success: PositionCallback) => success({ coords: { latitude: 17.385, longitude: 78.486 } } as GeolocationPosition));
    vi.stubGlobal('navigator', { ...navigator, geolocation: { getCurrentPosition } });
    window.history.replaceState({}, '', '/my-farm-today');
    render(<App />);
    expect(getCurrentPosition).not.toHaveBeenCalled();
    fireEvent.change(await screen.findByLabelText('Your state'), { target: { value: 'Telangana' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Warangal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Use current location' }));
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole('status')).toHaveTextContent(/We found your current location/);
    fireEvent.click(screen.getByRole('button', { name: 'Get weather' }));
    expect(await screen.findByText(/Warangal, Hanamkonda, Telangana, India/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Weather for the next 1 day' })).toBeInTheDocument();
    expect(screen.getByText('Chance of rain')).toBeInTheDocument();
    expect(screen.queryByText(/Geographic resolution|Forecast model|non-commercial|request limits|Model time/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Listen to weather' })).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toMatchObject({ state: 'Telangana', district: 'Warangal' });
    expect(JSON.parse(fetchMock.mock.calls[2]?.[1]?.body as string)).toMatchObject({ state: 'Telangana', district: 'Warangal' });
    const weatherRequest = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/farm/today'));
    expect(JSON.parse(String(weatherRequest?.[1]?.body))).toMatchObject({ latitude: 17.385, longitude: 78.486, state: 'Telangana', district: 'Warangal' });
  });

  it('does not show fictional mock weather as real conditions', async () => {
    const mock = { location: 'Demo', state: 'Telangana', district: 'Demo', current: { temperature_c: 27 }, forecast: [{ date: '2030-01-01', summary: 'Fictional sun', temperature_c: 27, precipitation_mm: 0 }], advice: [], alerts: [], source: 'Fictional sample', is_mock: true, notice: 'fictional' };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => ({ ok: true, json: async () => String(input).includes('/farm/today') ? mock : String(input).includes('/conversations') ? { conversation_id: 'sample', language: 'en-IN', language_status: 'unverified', language_notice: '' } : { status: 'ok', environment: 'test', providers: {} } } as Response));
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState({}, '', '/my-farm-today');
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Your state'), { target: { value: 'Telangana' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Warangal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get weather' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Weather is not available right now/);
    expect(screen.queryByText('27°C')).not.toBeInTheDocument();
    expect(screen.queryByText('2030')).not.toBeInTheDocument();
  });

  it('hides weather values that the provider did not return', async () => {
    const sparse = { location: 'Demo', state: 'Telangana', district: 'Demo', resolved_place: 'Demo, Telangana', current: { temperature_c: null, relative_humidity_percent: null, precipitation_mm: null, wind_speed_kmh: null }, forecast: [{ date: '2026-11-03', summary: 'Weather summary unavailable', temperature_c: null, temperature_min_c: null, precipitation_mm: null, precipitation_probability: null }], advice: [], alerts: [], warnings_available: false, is_mock: false, source: 'Open-Meteo', fetched_at: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => ({ ok: true, json: async () => String(input).includes('/farm/today') ? sparse : String(input).includes('/conversations') ? { conversation_id: 'sparse', language: 'en-IN', language_status: 'unverified', language_notice: '' } : { status: 'ok', environment: 'test', providers: {} } } as Response));
    vi.stubGlobal('fetch', fetchMock);
    window.history.replaceState({}, '', '/my-farm-today');
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Your state'), { target: { value: 'Telangana' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Warangal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Get weather' }));
    expect(await screen.findByText(/Weather near Demo, Telangana/)).toBeInTheDocument();
    expect(screen.queryByText('Temperature')).not.toBeInTheDocument();
    expect(screen.queryByText('Chance of rain')).not.toBeInTheDocument();
    expect(screen.queryByText('Expected rain')).not.toBeInTheDocument();
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('keeps typed-input routing available', async () => {
    const fetchMock = routeFetch('MY_FARM_TODAY', 'my-farm-today');
    render(<App />);
    fireEvent.change(await screen.findByLabelText('Or type a request'), { target: { value: 'What will the weather be like tomorrow?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).message).toBe('What will the weather be like tomorrow?');
  });

  it('uses only the Prisma recording upload path and keeps the transcript reviewable', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'te', languageChosen: true }));
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) } });
    class FakeRecorder {
      state = 'inactive'; mimeType = 'audio/webm'; ondataavailable: ((event: { data: Blob }) => void) | null = null; onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['recorded bytes'], { type: this.mimeType }) }); this.onstop?.(); }
    }
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: class {
      async decodeAudioData() { return { duration: 0.05, sampleRate: 16000, numberOfChannels: 1, getChannelData: () => new Float32Array(800) }; }
      async close() {}
    } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requests.push({ url, init });
      if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: true, prisma_input_enabled: true, timbre_output_enabled: true }) } as Response;
      if (url.endsWith('/voice/conversations')) return { ok: true, json: async () => ({ conversation_id: 'prisma-session', language: 'te', language_status: 'supported', history: [] }) } as Response;
      if (url.endsWith('/audio')) return { ok: true, json: async () => ({ accepted: true, transcribed: true, text: 'రేపు వర్షం పడుతుందా?', language: 'te-IN', is_mock: false, notice: 'Transcribed by Prisma.' }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    const browserRecognition = vi.fn(() => { throw new Error('Browser STT must not be used'); });
    vi.stubGlobal('SpeechRecognition', browserRecognition);
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'మాట్లాడండి' }));
    fireEvent.click(await screen.findByRole('button', { name: 'మాట్లాడటం ముగించండి' }));
    expect(await screen.findByLabelText('లేదా మీ ప్రశ్న రాయండి')).toHaveValue('రేపు వర్షం పడుతుందా?');
    expect(requests.filter((request) => request.url.endsWith('/audio'))).toHaveLength(1);
    expect(requests.some((request) => request.url.endsWith('/messages'))).toBe(false);
    expect((requests.find((request) => request.url.endsWith('/audio'))?.init?.headers as Record<string, string>)['Content-Type']).toBe('audio/wav');
    expect(browserRecognition).not.toHaveBeenCalled();
  });

  it('reports microphone permission denial and leaves text input usable', async () => {
    const denied = new DOMException('denied', 'NotAllowedError');
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(denied) } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: true, prisma_input_enabled: true, timbre_output_enabled: false }) }));
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Start listening' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Microphone unavailable/);
    expect(screen.getByLabelText('Or type a request')).toBeInTheDocument();
  });

  it('contains no wake listener, browser recognizer control or wake activation UI', async () => {
    vi.stubGlobal('SpeechRecognition', vi.fn(() => { throw new Error('Browser STT must not be used'); }));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {}, gnani_live_api_enabled: false, prisma_input_enabled: false, timbre_output_enabled: false }) }));
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Open assistant chat' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open assistant chat' }));
    expect(screen.queryByText(/wake phrase|persistent voice|on-device recognition/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Start listening/)).not.toBeInTheDocument();
  });

  it('starts a fresh session if the backend forgot the previous in-memory conversation', async () => {
    const payload = (id: string) => ({ ok: true, json: async () => ({ conversation_id: id, language: 'en-IN', language_status: 'unverified', language_notice: 'notice' }) });
    const turn = { conversation_id: 'c', language: 'en-IN', feature_implemented: false, feature_notice: 'This feature page is a Stage 2 integration placeholder. No agricultural result was generated.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.82, clarification_required: false, response: 'No live farm results are available.', language: 'en-IN', response_language: 'en-IN', is_mock: true, source: 'local rules' } };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) })
      .mockResolvedValueOnce(payload('old'))
      .mockResolvedValueOnce({ ok: true, json: async () => turn })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ error: { code: 'http_error', message: 'Conversation not found. Start a new conversation.' } }) })
      .mockResolvedValueOnce(payload('new'))
      .mockResolvedValueOnce({ ok: true, json: async () => turn });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Will it rain tomorrow?' }));
    await screen.findByRole('heading', { name: 'Weather' });
    fireEvent.click(screen.getByRole('link', { name: '← Ask another question' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Will it rain tomorrow?' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it('keeps the chosen language and feature names across navigation', async () => {
    render(<App />);
    const select = document.querySelector('.global-language select') as HTMLSelectElement;
    const labels: Record<string,string> = { te: 'వాతావరణం', en: 'Weather', hi: 'मौसम', ta: 'வானிலை', kn: 'ಹವಾಮಾನ', ml: 'കാലാവസ്ഥ', mr: 'हवामान' };
    for (const [language, label] of Object.entries(labels)) {
      fireEvent.change(select, { target: { value: language } });
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
    }
    fireEvent.change(select, { target: { value: 'kn' } });
    const checkLabel = 'ಬೆಳೆಯನ್ನು ಪರಿಶೀಲಿಸಿ';
    fireEvent.click(screen.getByRole('link', { name: checkLabel }));
    expect(await screen.findByRole('heading', { name: checkLabel })).toBeInTheDocument();
    expect((document.querySelector('.global-language select') as HTMLSelectElement).value).toBe('kn');
    expect(localStorage.getItem('kisan-hita-session')).toContain('kn');
  });

  it('submits the Choose My Crop details and shows the honest data limitation', async () => {
    window.history.replaceState({}, '', '/choose-my-crop');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'crop-1', language: 'en', history: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'crop-1', language: 'en', feature_implemented: true, feature_notice: 'No verified data.', result: { intent: 'CHOOSE_MY_CROP', destination: 'choose-my-crop', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8, clarification_required: false, response: 'Verified local crop information is not available.', language: 'en', response_language: 'en', is_mock: true, source: 'No source configured', tool_name: 'choose-my-crop', tool_result: { status: 'no_verified_data', source: 'No source configured' }, answer_supported: false, answer_mode: 'deterministic-grounded-template' } }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('Your state'), { target: { value: 'Telangana' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Warangal' } });
    fireEvent.change(screen.getByLabelText('Growing season'), { target: { value: 'monsoon' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check what information is available' }));
    expect((await screen.findAllByText('Verified local crop information is not available.')).length).toBeGreaterThan(0);
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.message).toContain('crop');
    expect(body.tool_arguments.district).toBe('Warangal');
    expect(body.tool_arguments.season).toBe('monsoon');
  });

  it('requires only district and season and blocks whitespace-only details', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'en', languageChosen: true }));
    window.history.replaceState({}, '', '/choose-my-crop');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    const district = screen.getByLabelText('Your district or town') as HTMLSelectElement;
    const season = screen.getByLabelText('Growing season') as HTMLInputElement;
    expect(district.required).toBe(true);
    expect(season.required).toBe(true);
    expect(screen.getByLabelText('Soil type')).not.toBeRequired();
    expect(screen.getByLabelText('Water available')).not.toBeRequired();
    fireEvent.change(season, { target: { value: '  ' } });
    fireEvent.submit(district.closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter your district or town and growing season/);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/voice/conversations'))).toBe(false);
  });

  it('shows Telugu regional context without presenting it as a recommendation and restores entered details', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'te', languageChosen: true }));
    window.history.replaceState({}, '', '/choose-my-crop');
    const regionalContext = {
      region: 'Central Telangana Zone', crops_reported: ['cotton', 'rice', 'maize', 'greengram', 'mango', 'sugarcane', 'chillies'],
      annual_rainfall_range_mm: '779–1,213', zone_soil_summary: 'red soils (zone-level summary)',
      source_period: 'Telangana Statistical Abstract 2021; crop pattern reference year 2020–21',
      source: 'Government of Telangana, Telangana State Statistical Abstract 2021',
      source_url: 'https://example.test/official-report.pdf',
      limitation: 'Historical zone-level context only; not a farm-specific recommendation.',
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) } as Response;
      if (url.endsWith('/voice/conversations') && init?.method === 'POST') return { ok: true, json: async () => ({ conversation_id: 'crop-te', language: 'te', history: [] }) } as Response;
      if (url.endsWith('/messages')) return { ok: true, json: async () => ({
        conversation_id: 'crop-te', language: 'te', feature_implemented: true,
        feature_notice: 'మీ ప్రశ్నకు అందుబాటులో ఉన్న సమాచారంతో ఈ సమాధానం ఇచ్చాను.',
        result: { intent: 'CHOOSE_MY_CROP', destination: 'choose-my-crop', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8,
          clarification_required: false, response: 'సురక్షితంగా పంటను సూచించడానికి మీ ప్రాంతానికి సంబంధించిన నమ్మకమైన సమాచారం లేదు.',
          language: 'te', response_language: 'te', is_mock: true, source: 'No verified data', tool_name: 'choose-my-crop',
          tool_result: { status: 'regional_context_only', source: regionalContext.source, regional_context: regionalContext },
          answer_supported: false, answer_mode: 'deterministic-grounded-template' },
      }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    const first = render(<App />);
    fireEvent.change(document.getElementById('crop-state')!, { target: { value: 'Telangana' } });
    fireEvent.change(document.getElementById('crop-district')!, { target: { value: 'Warangal' } });
    fireEvent.change(document.getElementById('crop-season')!, { target: { value: 'వర్షాకాలం' } });
    fireEvent.submit(document.querySelector('.feature-workflow .workflow-form')!);
    expect(await screen.findByText('పత్తి, వరి, మొక్కజొన్న, పెసలు, మామిడి, చెరకు, మిరప')).toBeInTheDocument();
    expect(screen.getByText(/సురక్షితంగా పంటను సూచించడానికి/)).toBeInTheDocument();
    expect(screen.getByText(/ఈ పాత ప్రాంత జాబితా/)).toBeInTheDocument();
    expect(screen.queryByText('cotton, rice, maize, greengram, mango, sugarcane, chillies')).not.toBeInTheDocument();
    expect(screen.queryByText(/crop pattern reference year/)).not.toBeInTheDocument();
    const conversation = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/voice/conversations'))!;
    expect(JSON.parse(String(conversation[1]?.body)).language).toBe('te');
    const message = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/messages'))!;
    expect(JSON.parse(String(message[1]?.body)).tool_arguments).toMatchObject({ state: 'Telangana', district: 'Warangal', season: 'వర్షాకాలం' });
    expect(JSON.parse(localStorage.getItem('kisan-hita-session')!).session.crop_details).toMatchObject({ district: 'Warangal', season: 'వర్షాకాలం' });

    first.unmount();
    render(<App />);
    expect((document.getElementById('crop-district') as HTMLInputElement).value).toBe('Warangal');
    expect((document.getElementById('crop-season') as HTMLInputElement).value).toBe('వర్షాకాలం');
    expect((document.getElementById('crop-state') as HTMLSelectElement).value).toBe('Telangana');
  });

  it('renders verified crop results with publication, review, geography, season, and conditions', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'en', languageChosen: true }));
    window.history.replaceState({}, '', '/choose-my-crop');
    const evidence = {
      evidence_id: 'test-current-guide', source_title: 'Reviewed crop guide', publisher: 'PJTSAU',
      source_url: 'https://example.test/reviewed-guide.pdf', evidence_type: 'current_recommendation',
      publication_year: 2025, publication_date: '2025-05-01', reviewed_on: '2026-06-01',
      valid_from: '2025-06-01', valid_until: '2026-12-31', geography: 'Warangal district',
      season: 'Kharif', conditions: ['Red soil', 'Limited water'],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) } as Response;
      if (url.endsWith('/voice/conversations') && init?.method === 'POST') return { ok: true, json: async () => ({ conversation_id: 'crop-evidence-en', language: 'en', history: [] }) } as Response;
      if (url.endsWith('/messages')) return { ok: true, json: async () => ({
        conversation_id: 'crop-evidence-en', language: 'en', feature_implemented: true,
        feature_notice: 'This response uses the information available for your question.',
        result: { intent: 'CHOOSE_MY_CROP', destination: 'choose-my-crop', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8,
          clarification_required: false, response: 'Verified crop guidance is available for the details you entered.',
          language: 'en', response_language: 'en', is_mock: false, source: 'PJTSAU', tool_name: 'choose-my-crop',
          tool_result: { outcome: 'verified_recommendation', status: 'verified_recommendation', source: 'PJTSAU',
            recommendations: [{ crop: 'Test crop', reasons: ['The cited source lists this crop for these conditions.'], cultivation_notes: [] }],
            evidence: [evidence], catalog_version: 'test-only' },
          answer_supported: true, answer_mode: 'deterministic-grounded-template' },
      }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(document.getElementById('crop-state')!, { target: { value: 'Telangana' } });
    fireEvent.change(document.getElementById('crop-district')!, { target: { value: 'Warangal' } });
    fireEvent.change(document.getElementById('crop-season')!, { target: { value: 'monsoon' } });
    fireEvent.change(document.getElementById('crop-soil')!, { target: { value: 'Red soil' } });
    fireEvent.change(document.getElementById('crop-water')!, { target: { value: 'limited' } });
    fireEvent.submit(document.querySelector('.feature-workflow .workflow-form')!);
    expect(await screen.findByRole('heading', { name: 'Test crop' })).toBeInTheDocument();
    expect(screen.getByText('Reviewed crop guide')).toHaveAttribute('href', evidence.source_url);
    expect(screen.getByText('Published: 2025-05-01')).toBeInTheDocument();
    expect(screen.getByText('Reviewed: 2026-06-01')).toBeInTheDocument();
    expect(screen.getByText('Applies during: 2025-06-01 - 2026-12-31')).toBeInTheDocument();
    expect(screen.getByText('Applies to: Warangal district')).toBeInTheDocument();
    expect(screen.getByText('Season: Kharif')).toBeInTheDocument();
    expect(screen.getByText('For these conditions: Red soil; Limited water')).toBeInTheDocument();
    expect(screen.queryByText(/yield|profit|income/i)).not.toBeInTheDocument();
  });

  it('does not render a recommendation unless the backend marks it verified', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'en', languageChosen: true }));
    window.history.replaceState({}, '', '/choose-my-crop');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) } as Response;
      if (url.endsWith('/voice/conversations') && init?.method === 'POST') return { ok: true, json: async () => ({ conversation_id: 'crop-not-verified', language: 'en', history: [] }) } as Response;
      if (url.endsWith('/messages')) return { ok: true, json: async () => ({
        conversation_id: 'crop-not-verified', language: 'en', feature_implemented: true, feature_notice: 'No verified advice.',
        result: { intent: 'CHOOSE_MY_CROP', destination: 'choose-my-crop', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8,
          clarification_required: false, response: 'I can’t find current crop guidance for this district and season.', language: 'en', response_language: 'en', is_mock: true,
          source: 'test only', tool_name: 'choose-my-crop', tool_result: { outcome: 'no_applicable_evidence', recommendations: [{ crop: 'Unsupported crop', reasons: ['not verified'], cultivation_notes: [] }] },
          answer_supported: false, answer_mode: 'deterministic-grounded-template' },
      }) } as Response;
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(document.getElementById('crop-state')!, { target: { value: 'Telangana' } });
    fireEvent.change(document.getElementById('crop-district')!, { target: { value: 'Warangal' } });
    fireEvent.change(document.getElementById('crop-season')!, { target: { value: 'monsoon' } });
    fireEvent.submit(document.querySelector('.feature-workflow .workflow-form')!);
    expect(await screen.findByText(/can’t find current crop guidance/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Unsupported crop' })).not.toBeInTheDocument();
  });

  it('uploads an actual crop image and shows that no diagnosis was made', async () => {
    window.history.replaceState({}, '', '/check-my-crop');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'crop-photo-1', language: 'en', history: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ possible_conditions: [], guidance: [], needs_expert: true, uncertainty: 'No diagnosis was made.', source: 'No model', is_mock: false, agent_answer: 'Your photo was received, but no diagnosis was made.' }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    const image = new File(['\x89PNG\r\n\x1a\nfixture'], 'leaf.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Choose a crop photo'), { target: { files: [image] } });
    fireEvent.change(screen.getByLabelText('What changes have you noticed?'), { target: { value: 'Spots on leaves' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send photo and details' })).toBeEnabled());
    fireEvent.submit(screen.getByRole('button', { name: 'Send photo and details' }).closest('form')!);
    expect(await screen.findByText(/cannot identify crop problems from images yet/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain('conversation_id=crop-photo-1');
    expect(fetchMock.mock.calls[1][1].body).toBe(image);
  });

  it('shows a validation explanation for HTTP 422 instead of a connection error', async () => {
    window.history.replaceState({}, '', '/check-my-crop');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'crop-invalid', language: 'en', history: [] }) })
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ error: { code: 'http_error', message: 'This file doesn’t look like a PNG image.' } }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    const image = new File(['not an image'], 'leaf.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Choose a crop photo'), { target: { files: [image] } });
    fireEvent.change(screen.getByLabelText('What changes have you noticed?'), { target: { value: 'Spots on leaves' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Send photo and details' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('This file does not match the image format selected');
    expect(screen.getByRole('alert')).not.toHaveTextContent('connect');
  });

  it('accepts a symptom-only crop report without pretending to diagnose it', async () => {
    window.history.replaceState({}, '', '/check-my-crop');
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'symptom-only', language: 'en', history: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('Which part of the plant is affected?'), { target: { value: 'affectedLeaves' } });
    fireEvent.change(screen.getByLabelText('What do you see?'), { target: { value: 'symptomSpots' } });
    fireEvent.click(document.querySelector('.feature-workflow .workflow-form button[type="submit"]')!);
    expect((await screen.findAllByText(/This is a symptom record/)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/not a diagnosis or treatment recommendation/)).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('kisan-hita-session')).toContain('Leaves');
  });

  it('shows no price when the market source has no verified live data', async () => {
    window.history.replaceState({}, '', '/market-prices');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'market-1', language: 'en', history: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'market-1', language: 'en', feature_implemented: true, feature_notice: 'No verified price.', result: { intent: 'MARKET_PRICES', destination: 'market-prices', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8, clarification_required: false, response: 'No matching price record is available. DEMO sample records are not live market data.', language: 'en', response_language: 'en', is_mock: true, source: 'No live feed', tool_name: 'market-prices', tool_result: { status: 'no_verified_data', source: 'No live feed', prices: [] }, answer_supported: false, answer_mode: 'deterministic-grounded-template' } }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('Crop or commodity'), { target: { value: 'cotton' } });
    fireEvent.change(screen.getByLabelText('Your state'), { target: { value: 'Telangana' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Warangal' } });
    fireEvent.change(screen.getByLabelText('Market or town'), { target: { value: 'Warangal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check prices' }));
    expect((await screen.findAllByText('No matching price record is available.')).length).toBeGreaterThan(0);
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.tool_arguments).toMatchObject({ crop: 'cotton', market: 'Warangal', state: 'Telangana', district: 'Warangal' });
    expect(screen.queryByText(/₹|Rs\.?\s*\d/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DEMO sample records|not live market data/i)).not.toBeInTheDocument();
  });

  it('keeps market facts while omitting demo and source description lines from populated results', async () => {
    localStorage.clear();
    window.history.replaceState({}, '', '/market-prices');
    const record = { crop: 'chilli', market: 'Guntur APMC Yard', price: 19800, minimum_price: 18000, maximum_price: 21000, modal_price: 19800, unit: '₹/quintal', observed_at: '2026-11-04', source: 'Demo Reference Record — Not Live Market Data — APMC Market Yard', is_mock: true };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'market-ui', language: 'en', history: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'market-ui', language: 'en', feature_implemented: true, feature_notice: 'no extra notice', result: { intent: 'MARKET_PRICES', destination: 'market-prices', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.8, clarification_required: false, response: 'DEMO sample records, not live market data.', language: 'en', response_language: 'en', is_mock: true, source: 'demo', tool_name: 'market-prices', tool_result: { prices: [record] }, answer_supported: true, answer_mode: 'deterministic-grounded-template' } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'market-ui', language: 'kn', history: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('Crop or commodity'), { target: { value: 'chilli' } });
    fireEvent.change(screen.getByLabelText('Your state'), { target: { value: 'Andhra Pradesh' } });
    fireEvent.change(screen.getByLabelText('Your district or town'), { target: { value: 'Sri Potti Sriramulu Nellore' } });
    fireEvent.change(screen.getByLabelText('Market or town'), { target: { value: 'Guntur' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check prices' }));
    expect(await screen.findByRole('heading', { name: /Guntur APMC Yard/ })).toBeInTheDocument();
    expect(screen.getAllByText(/19,800|19800/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/₹\/quintal/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Price date: 11\/4\/2026|Price date: Nov 4, 2026/)).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).tool_arguments.crop).toBe('chilli');
    fireEvent.change(screen.getByLabelText('Choose a language'), { target: { value: 'kn' } });
    expect(await screen.findByRole('heading', { name: 'ಮೆಣಸಿನಕಾಯಿ — Guntur APMC Yard' })).toBeInTheDocument();
    expect(screen.queryByText(/DEMO sample records|Not Live Market Data|Demo Reference Record|APMC Market Yard/)).not.toBeInTheDocument();
  });

  it('routes a typed assistant question to Weather and keeps the answer visible', async () => {
    window.history.replaceState({}, '', '/ask-kisan-hita');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'typed-1', language: 'en', language_status: 'unverified', language_notice: 'Voice unavailable', history: [] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'typed-1', language: 'en', feature_implemented: true, feature_notice: 'Choose your farm state and district to check its forecast.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: ['location'], confidence: 0.82, clarification_required: true, response: 'I cannot check a forecast until you choose your farm location.', language: 'en', response_language: 'en', is_mock: true, source: 'local rules', tool_name: 'my-farm-today', tool_result: { status: 'needs_location' }, answer_supported: false, answer_mode: 'deterministic-grounded-template' } }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Open assistant chat' }));
    fireEvent.change(screen.getByLabelText('Type your question'), { target: { value: 'Will it rain tomorrow?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(screen.getAllByText('I cannot check a forecast until you choose your farm location.').length).toBeGreaterThan(0);
  });

  it('asks for a first language and persists language and custom assistant name', async () => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) }));
    const { unmount } = render(<App />);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Your language'), { target: { value: 'mr' } });
    fireEvent.click(screen.getByRole('button', { name: 'पुढे चला' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'सहाय्यक चॅट उघडा' }));
    fireEvent.click(screen.getByRole('button', { name: 'सेटिंग्ज' }));
    fireEvent.change(screen.getByLabelText('सहाय्यकाचे नाव'), { target: { value: 'Sheti Mitra' } });
    expect(JSON.parse(localStorage.getItem('kisan-hita-preferences')!)).toMatchObject({ language: 'mr', languageChosen: true, assistantName: 'Sheti Mitra' });
    unmount();
    render(<App />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'सहाय्यक चॅट उघडा' })).toHaveTextContent('Sheti Mitra');
    fireEvent.click(screen.getByRole('button', { name: 'सहाय्यक चॅट उघडा' }));
    fireEvent.click(screen.getByRole('button', { name: 'सेटिंग्ज' }));
    expect(document.querySelector('.assistant-settings input[type="checkbox"]')).toBeNull();
  });

  it('keeps the assistant panel and conversation across feature navigation and follow-up questions', async () => {
    localStorage.clear();
    localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language: 'en', languageChosen: true, assistantName: 'Kisan Hita' }));
    window.history.replaceState({}, '', '/ask-kisan-hita');
    const response = (message: string) => ({ ok: true, json: async () => ({ conversation_id: 'shared-session', language: 'en', feature_implemented: true, feature_notice: 'Please choose your farm location.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: ['state', 'district'], confidence: 0.9, clarification_required: true, response: message, language: 'en', response_language: 'en', is_mock: true, source: 'local rules', tool_name: 'my-farm-today', tool_result: { status: 'needs_location' }, answer_supported: false, answer_mode: 'deterministic-grounded-template' } }) });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ conversation_id: 'shared-session', language: 'en', language_status: 'supported', history: [] }) })
      .mockImplementationOnce(async (_url: RequestInfo | URL, _init?: RequestInit) => response('Which state and district is your farm in?'))
      .mockImplementationOnce(async (_url: RequestInfo | URL, _init?: RequestInit) => response('I have noted your farm location.'));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Open assistant chat' }));
    fireEvent.change(screen.getByLabelText('Type your question'), { target: { value: 'Will it rain on my farm tomorrow?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByRole('heading', { name: 'Weather' })).toBeInTheDocument();
    expect(screen.getByLabelText('Your state')).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Kisan Hita' })).toBeInTheDocument();
    expect((await screen.findAllByText('Which state and district is your farm in?')).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText('Type your question'), { target: { value: 'Telangana, Warangal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const followup = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(followup).toMatchObject({ message: 'Telangana, Warangal' });
    expect(String(fetchMock.mock.calls[2][0])).toContain('/voice/conversations/shared-session/messages');
    expect(screen.getByText('Will it rain on my farm tomorrow?')).toBeInTheDocument();
    expect((await screen.findAllByText('I have noted your farm location.')).length).toBeGreaterThan(0);
  });

  it('shows the selected-language mismatch fallback on the routed feature in every locale', async () => {
    const sourceResponse = 'This source answer is intentionally in English.';
    for (const language of supportedLocales) {
      cleanup();
      localStorage.clear();
      localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language, languageChosen: true, assistantName: 'Kisan Hita' }));
      window.history.replaceState({}, '', '/');
      const turn = { conversation_id: `mismatch-${language}`, language, feature_implemented: true, feature_notice: 'Fixture notice.', result: { intent: 'MY_FARM_TODAY', destination: 'my-farm-today', entities: {}, required_parameters: [], missing_parameters: [], confidence: 0.9, clarification_required: false, response: sourceResponse, language: 'en', response_language: 'en', is_mock: language === 'en', source: 'local fixture' } };
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/health')) return { ok: true, json: async () => ({ status: 'ok', environment: 'test', providers: {} }) } as Response;
        if (url.endsWith('/voice/conversations')) return { ok: true, json: async () => ({ conversation_id: `mismatch-${language}`, language, language_status: 'supported', history: [] }) } as Response;
        if (url.includes('/voice/conversations/') && url.endsWith('/messages')) return { ok: true, json: async () => turn } as Response;
        if (url.endsWith('/speech')) return { ok: true, json: async () => ({ available: false, audio_base64: '', is_mock: true }) } as Response;
        throw new Error(`Unexpected local test request: ${url}`);
      });
      vi.stubGlobal('fetch', fetchMock);
      render(<App />);
      fireEvent.click(screen.getByRole('button', { name: messages[language].openAssistant }));
      fireEvent.change(screen.getByLabelText(messages[language].typeQuestion), { target: { value: 'Will it rain tomorrow?' } });
      fireEvent.click(screen.getByRole('button', { name: messages[language].send }));
      const shown = language === 'en' ? sourceResponse : translate(language, 'responseLanguageUnavailable');
      expect((await screen.findAllByText(shown)).length).toBeGreaterThan(0);
      expect(screen.getByLabelText(messages[language].typeQuestion)).toBeInTheDocument();
      expect(turn.result.response).toBe(sourceResponse);
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/speech'))).toBe(language !== 'en');
    }
  });
});
