import { createContext, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { BrowserRouter, Link, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Layout, featureRoutes } from '../components/Layout';
import { askAssistant, createVoiceConversation, getCropRecommendations, getFarmToday, getHealth, getMarketPrices, localizedApiError, saveFarmLocation, sendCropPhoto, sendVoiceAudio, sendVoiceMessage, setConversationLanguage, synthesizeVoice } from '../services/api';
import { assistantResponseForLanguage, localizeCropName, localizeKnownLocation, messages, translate, type Locale } from '../localization';
import type { CropResponse, FarmTodayResponse, MarketLookupResponse, VoiceConversation, VoiceTurn } from '../types/api';
import { makeWavBlob } from '../services/audio';
import { districtsForStateCode, geographicDisplayName, indianGeography, stateByCanonicalName, districtByCanonicalName } from '../data/geography';
import { prismaInputEnabled } from '../services/speech';

type Phase = 'IDLE' | 'LISTENING' | 'TRANSCRIBING' | 'UNDERSTANDING' | 'NAVIGATING' | 'PROCESSING' | 'ERROR';
type VoiceSessionContextValue = { session: VoiceConversation | null; setSession: (session: VoiceConversation | null) => void; language: string; setLanguage: (language: string) => void; assistantName: string; setAssistantName: (name: string) => void; languageChosen: boolean; setLanguageChosen: (chosen: boolean) => void };
const VoiceSessionContext = createContext<VoiceSessionContextValue | null>(null);

function VoiceSessionProvider({ children }: { children: ReactNode }) {
  const [saved] = useState(() => { try { return JSON.parse(localStorage.getItem('kisan-hita-session') ?? 'null') as { session: VoiceConversation | null; language: string } | null; } catch { return null; } });
  const [preferences] = useState(() => { try { return JSON.parse(localStorage.getItem('kisan-hita-preferences') ?? 'null') as { language?: string; assistantName?: string; languageChosen?: boolean } | null; } catch { return null; } });
  const [session, setSession] = useState<VoiceConversation | null>(saved?.session ?? null);
  const [language, setLanguage] = useState(preferences?.language ?? saved?.language ?? 'en');
  const [assistantName, setAssistantName] = useState(preferences?.assistantName?.trim() || 'Kisan Hita');
  const [languageChosen, setLanguageChosen] = useState(preferences?.languageChosen ?? false);
  useEffect(() => { localStorage.setItem('kisan-hita-session', JSON.stringify({ session, language })); }, [session, language]);
  useEffect(() => { localStorage.setItem('kisan-hita-preferences', JSON.stringify({ language, assistantName, languageChosen })); }, [language, assistantName, languageChosen]);
  return <VoiceSessionContext.Provider value={{ session, setSession, language, setLanguage, assistantName, setAssistantName, languageChosen, setLanguageChosen }}>{children}</VoiceSessionContext.Provider>;
}

function AppLayout() {
  const { language, setLanguage, session, setSession, setLanguageChosen } = useVoiceSession();
  async function changeLanguage(next: Locale) {
    setLanguage(next);
    setLanguageChosen(true);
    if (session) {
      try { setSession(await setConversationLanguage(session.conversation_id, next)); }
      catch { setSession({ ...session, language: next }); }
    }
  }
  return <><Layout language={language as Locale} onLanguageChange={(next) => void changeLanguage(next)} /><AssistantDock /><LanguageWelcome /></>;
}

function LanguageWelcome() {
  const { language, setLanguage, setLanguageChosen, languageChosen, session, setSession } = useVoiceSession();
  if (languageChosen) return null;
  async function choose(next: Locale) { setLanguage(next); setLanguageChosen(true); if (session) { try { setSession(await setConversationLanguage(session.conversation_id,next)); } catch { setSession({...session,language:next}); } } }
  return <div className="language-welcome-backdrop"><section className="language-welcome" role="dialog" aria-modal="true" aria-labelledby="language-welcome-title"><h2 id="language-welcome-title">{translate(language,'welcomeLanguageTitle')}</h2><p>{translate(language,'welcomeLanguageBody')}</p><label htmlFor="welcome-language">{translate(language,'comfortableLanguage')}</label><select id="welcome-language" value={language} onChange={(event)=>setLanguage(event.target.value)}><option value="te">తెలుగు</option><option value="en">English</option><option value="hi">हिन्दी</option><option value="ta">தமிழ்</option><option value="kn">ಕನ್ನಡ</option><option value="ml">മലയാളം</option><option value="mr">मराठी</option></select><button type="button" onClick={()=>choose(language as Locale)}>{translate(language,'continueButton')}</button></section></div>;
}

function useVoiceSession() {
  const value = useContext(VoiceSessionContext);
  if (!value) throw new Error('Voice session context is missing.');
  return value;
}

async function runAgentTurn(current: VoiceConversation | null, language: string, message: string,
                            toolArguments: Record<string, unknown> = {}) {
  let active = current ?? await createVoiceConversation(language);
  let turn: VoiceTurn;
  try {
    turn = await sendVoiceMessage(active.conversation_id, message, undefined, undefined, toolArguments);
  } catch (reason) {
    if (!(reason instanceof Error) || !reason.message.includes('Conversation not found')) throw reason;
    active = await createVoiceConversation(language);
    turn = await sendVoiceMessage(active.conversation_id, message, undefined, undefined, toolArguments);
  }
  const displayResponse = assistantResponseForLanguage(turn.result.response, turn.result.response_language ?? turn.result.language, language);
  const history = [...(active.history ?? []), { role: 'farmer', text: message }, { role: 'assistant', text: displayResponse }];
  return { session: { ...active, language, history }, turn };
}

function VoiceHome() {
  const [connection, setConnection] = useState<'loading' | 'connected' | 'offline'>('loading');
  const [prismaEnabled, setPrismaEnabled] = useState(false);
  const [phase, setPhase] = useState<Phase>('IDLE');
  const [transcript, setTranscript] = useState('');
  const [transcriptReview, setTranscriptReview] = useState(false);
  const [error, setError] = useState('');
  const { session, setSession, language, assistantName } = useVoiceSession();
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const submitInProgress = useRef(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const stream = useRef<MediaStream | null>(null);
  const recordingLimit = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    getHealth().then((health) => {
      if (alive) { setConnection('connected'); setPrismaEnabled(prismaInputEnabled(health)); }
    }).catch(() => { if (alive) setConnection('offline'); });
    return () => {
      alive = false;
      if (recordingLimit.current) clearTimeout(recordingLimit.current);
      if (recorder.current) { recorder.current.onstop = null; if (recorder.current.state === 'recording') recorder.current.stop(); }
      stream.current?.getTracks().forEach((track) => track.stop());
      controller.current?.abort();
    };
  }, []);

  async function handleText(text: string) {
    const requestText = text.trim();
    if (!requestText || busy || submitInProgress.current) { if (!requestText) setError(translate(language, 'emptySpeech')); return; }
    submitInProgress.current = true; setTranscriptReview(false);
    setTranscript(requestText); setError(''); setPhase('UNDERSTANDING'); setBusy(true);
    controller.current = new AbortController();
    try {
      let active = session ?? await createVoiceConversation(language);
      if (!session) setSession(active);
      setPhase('PROCESSING');
      let turn: VoiceTurn;
      try { turn = await sendVoiceMessage(active.conversation_id, requestText, controller.current.signal); }
      catch (reason) {
        if (!(reason instanceof Error) || !reason.message.includes('Conversation not found')) throw reason;
        active = await createVoiceConversation(language); setSession(active);
        turn = await sendVoiceMessage(active.conversation_id, requestText, controller.current.signal);
      }
      const displayResponse = assistantResponseForLanguage(turn.result.response, turn.result.response_language ?? turn.result.language, language);
      const updatedHistory = [...(active.history ?? []), { role: 'farmer', text: requestText }, { role: 'assistant', text: displayResponse }];
      setSession({ ...active, history: updatedHistory });
      if (turn.result.clarification_required || turn.result.confidence < 0.5) {
        setError([displayResponse, turn.result.language_notice].filter(Boolean).join(' ')); setPhase('IDLE'); return;
      }
      setPhase('NAVIGATING');
      navigate(`/${turn.result.destination}`, { state: { turn, transcript: requestText } });
    } catch {
      if (controller.current.signal.aborted) return;
      setError(t.offline); setPhase('ERROR');
    } finally { setBusy(false); submitInProgress.current = false; }
  }

  async function uploadRecording(recording: Blob) {
    if (!recording.size) { setError(translate(language, 'audioUnavailable')); setPhase('ERROR'); return; }
    setPhase('TRANSCRIBING');
    try {
      const audio = await makeWavBlob(recording);
      const active = session ?? await createVoiceConversation(language);
      if (!session) setSession(active);
      const response = await sendVoiceAudio(active.conversation_id, audio);
      if (!response.transcribed || response.is_mock || !response.text.trim()) {
        setError(translate(language, 'audioUnavailable')); setPhase('ERROR'); return;
      }
      setTranscript(response.text); setError(''); setTranscriptReview(true); setPhase('IDLE');
    } catch (reason) {
      setError(reason instanceof Error && reason.message.includes('30 seconds')
        ? translate(language, 'audioTooLong')
        : localizedApiError(reason, language, '/voice/conversations/audio'));
      setPhase('ERROR');
    }
  }

  async function startPrismaRecording() {
    if (!prismaEnabled || busy || phase === 'LISTENING' || phase === 'TRANSCRIBING') return;
    setError(''); setTranscript(''); setTranscriptReview(false);
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('microphone-unavailable');
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks.current = [];
      const media = new MediaRecorder(stream.current);
      recorder.current = media;
      media.ondataavailable = (event) => { if (event.data.size) chunks.current.push(event.data); };
      media.onstop = () => {
        stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null; recorder.current = null;
        const captured = new Blob(chunks.current, { type: media.mimeType }); chunks.current = [];
        void uploadRecording(captured);
      };
      media.start(); setPhase('LISTENING');
      recordingLimit.current = setTimeout(() => finishRecording(), 29_500);
    } catch (reason) {
      stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null;
      setError(reason instanceof Error && reason.name === 'NotAllowedError'
        ? translate(language, 'microphoneDenied') : translate(language, 'micUnavailable'));
      setPhase('ERROR');
    }
  }

  function finishRecording() {
    if (recordingLimit.current) clearTimeout(recordingLimit.current);
    recordingLimit.current = null;
    if (recorder.current?.state === 'recording') { recorder.current.stop(); setPhase('TRANSCRIBING'); }
  }

  function cancelRecording() {
    if (recordingLimit.current) clearTimeout(recordingLimit.current);
    recordingLimit.current = null;
    if (recorder.current) { recorder.current.onstop = null; if (recorder.current.state === 'recording') recorder.current.stop(); }
    recorder.current = null; stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null; chunks.current = [];
    setPhase('IDLE'); setError(translate(language, 'stoppedListening'));
  }

  function stopRequest() { controller.current?.abort(); setBusy(false); setPhase('IDLE'); setError(translate(language, 'stoppedListening')); }
  function chooseSample(sample: string) { setTranscript(sample); void handleText(sample); }
  const capturing = phase === 'LISTENING' || phase === 'TRANSCRIBING';
  const status = phase === 'LISTENING' ? translate(language, 'listeningStatus')
    : phase === 'TRANSCRIBING' ? translate(language, 'transcribingAudio')
      : phase === 'UNDERSTANDING' ? translate(language, 'understandingStatus')
        : phase === 'PROCESSING' ? translate(language, 'processingStatus')
          : phase === 'NAVIGATING' ? translate(language, 'routingStatus')
            : phase === 'ERROR' ? error : transcriptReview ? translate(language, 'reviewTranscript') : t.ready;

  return <section className="voice-home">
    <p className="eyebrow">{messages[(language.split('-')[0] in messages ? language.split('-')[0] : 'en') as Locale].tagline}</p>
    <h1>{translate(language, 'ask')}</h1>
    <p className="intro voice-intro">{translate(language, 'general')}</p>
    <div className={`connection ${connection}`} role="status">{connection === 'loading' ? t.loading : connection === 'connected' ? t.connected : t.offline}</div>
    <div className={`voice-panel ${phase.toLowerCase()}`}>
      {prismaEnabled && <button className="mic-button" type="button" onClick={() => void startPrismaRecording()} disabled={busy || capturing} aria-label={translate(language, 'listen')}><span aria-hidden="true">🎙</span></button>}
      <p className="voice-status" role="status" aria-live="polite">{status}</p>
      {phase === 'LISTENING' && <button className="stop-button" type="button" onClick={finishRecording}>{translate(language, 'finish')}</button>}
      {capturing && <button className="cancel-button" type="button" onClick={cancelRecording}>{translate(language, 'cancel')}</button>}
      {busy && <button className="stop-button" type="button" onClick={stopRequest}>{translate(language, 'stop')}</button>}
      {transcript && <p className="transcript"><span>{translate(language, 'question')}:</span> “{transcript}”</p>}
      {error && <p className="voice-error" role="alert">{error}</p>}
      {!prismaEnabled && <p className="privacy-note">{translate(language, 'prismaUnavailable')}</p>}
      {prismaEnabled && <p className="privacy-note">{translate(language, 'privacy')}</p>}
    </div>
    <div className="typed-request"><label htmlFor="voice-request">{translate(language, 'typedRequest')}</label><form onSubmit={(event) => { event.preventDefault(); void handleText(transcript); }}><input id="voice-request" value={transcript} onChange={(event) => setTranscript(event.target.value)} placeholder={translate(language, 'sampleRain')}/><button type="submit" disabled={busy || !transcript.trim()}>{translate(language, 'askButton')}</button></form></div>
    <div className="language-row"><button type="button" className="new-conversation" onClick={() => { setSession(null); setTranscript(''); setError(''); setPhase('IDLE'); }}>{translate(language, 'newChat')}</button></div>
    {!!session?.history?.length && <section className="chat-history" aria-label={translate(language, 'conversationLabel')}><h2>{translate(language, 'conversationLabel')}</h2>{session.history.slice(-6).map((turn, index) => <p className={`chat-turn ${turn.role}`} key={`${index}-${turn.role}`}><strong>{turn.role === 'farmer' ? translate(language, 'question') : assistantName.trim() || t.appName}:</strong> {turn.text}</p>)}</section>}
    <div className="sample-area"><p>{translate(language, 'sampleArea')}</p><div className="sample-buttons"><button type="button" onClick={() => chooseSample(translate(language, 'sampleRain'))}>{translate(language, 'sampleRain')}</button><button type="button" onClick={() => chooseSample(translate(language, 'sampleCrop'))}>{translate(language, 'sampleCrop')}</button><button type="button" onClick={() => chooseSample(translate(language, 'sampleDisease'))}>{translate(language, 'sampleDisease')}</button><button type="button" onClick={() => chooseSample(translate(language, 'samplePrice'))}>{translate(language, 'samplePrice')}</button></div></div>
  </section>;
}
function AssistantDock() {
  const { session, setSession, language, setLanguage, assistantName, setAssistantName, setLanguageChosen } = useVoiceSession();
  const location = useLocation(); const navigate = useNavigate();
  const [message, setMessage] = useState(''); const [status, setStatus] = useState(''); const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false); const [settingsOpen, setSettingsOpen] = useState(false);
  const [answerAudio, setAnswerAudio] = useState(''); const [playing, setPlaying] = useState(false);
  const player = useRef<HTMLAudioElement | null>(null); const submitting = useRef(false); const lastSpokenTurn = useRef('');
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;

  useEffect(() => { const state = location.state as { turn?: VoiceTurn } | null; if (state?.turn) setOpen(true); }, [location.state]);
  useEffect(() => () => { player.current?.pause(); }, []);
  useEffect(() => {
    const routeState = location.state as { turn?: VoiceTurn; transcript?: string } | null;
    const turn = routeState?.turn;
    if (!turn || turn.result.is_mock) return;
    const key = `${turn.conversation_id}:${routeState?.transcript ?? ''}`;
    if (lastSpokenTurn.current === key) return;
    lastSpokenTurn.current = key;
    let cancelledRequest = false;
    const displayResponse = assistantResponseForLanguage(turn.result.response, turn.result.response_language ?? turn.result.language, language);
    void synthesizeVoice(turn.conversation_id, displayResponse).then(async (speech) => {
      if (cancelledRequest) return;
      if (!speech.available || speech.is_mock || !speech.audio_base64) { setStatus(translate(language, 'ttsUnavailable')); return; }
      const audioBytes = Uint8Array.from(atob(speech.audio_base64), (character) => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([audioBytes], { type: 'audio/wav' }));
      setAnswerAudio(url);
      const audio = new Audio(url); player.current = audio;
      audio.onended = () => { setPlaying(false); setStatus(translate(language, 'answerReady')); };
      audio.onerror = () => { setPlaying(false); setStatus(translate(language, 'playbackError')); };
      try { await audio.play(); setPlaying(true); setStatus(translate(language, 'playingAnswer')); }
      catch { setPlaying(false); setStatus(translate(language, 'playbackError')); }
    }).catch(() => { if (!cancelledRequest) setStatus(translate(language, 'ttsUnavailable')); });
    return () => { cancelledRequest = true; };
  }, [location.state, language]);
  useEffect(() => () => { if (answerAudio) URL.revokeObjectURL(answerAudio); }, [answerAudio]);

  async function submit(text: string): Promise<void> {
    const prompt = text.trim(); if (!prompt || busy || submitting.current) return;
    submitting.current = true; setBusy(true); setStatus(t.processingStatus);
    try {
      const { session: active, turn } = await runAgentTurn(session, language, prompt);
      setSession(active);
      const response = assistantResponseForLanguage(turn.result.response, turn.result.response_language ?? turn.result.language, language);
      setStatus(response);
      navigate(`/${turn.result.destination}`, { state: { turn, transcript: prompt } });
      setMessage('');
    } catch { setStatus(t.offline); }
    finally { setBusy(false); submitting.current = false; }
  }
  async function choosePanelLanguage(next: Locale) {
    setLanguage(next); setLanguageChosen(true);
    if (session) {
      try { setSession(await setConversationLanguage(session.conversation_id, next)); }
      catch { setSession({ ...session, language: next }); }
    }
  }
  function togglePlayback() {
    const audio = player.current;
    if (!audio) return;
    if (playing) { audio.pause(); setPlaying(false); setStatus(translate(language, 'answerReady')); return; }
    void audio.play().then(() => { setPlaying(true); setStatus(translate(language, 'playingAnswer')); })
      .catch(() => { setPlaying(false); setStatus(translate(language, 'playbackError')); });
  }

  return <>
    <button type="button" className={`assistant-launcher${open ? ' active' : ''}`} aria-label={open ? translate(language, 'closeAssistant') : translate(language, 'openAssistant')} aria-expanded={open} onClick={() => setOpen((value) => !value)}><span aria-hidden="true">✳</span><span className="assistant-launcher-label">{assistantName.trim() || t.appName}</span></button>
    {open && <aside className="assistant-dock" aria-label={assistantName.trim() || t.appName} role="complementary">
      <header className="assistant-panel-header"><div><strong>{assistantName.trim() || t.appName}</strong><span role="status">{status || t.ready}</span></div><div className="assistant-panel-actions"><button type="button" onClick={() => setSettingsOpen((value) => !value)} aria-expanded={settingsOpen}>{translate(language, 'assistantSettings')}</button><button type="button" onClick={() => setOpen(false)} aria-label={translate(language, 'closeAssistant')}>×</button></div></header>
      {settingsOpen && <section className="assistant-settings"><label htmlFor="assistant-display-name">{translate(language, 'assistantNameLabel')}</label><input id="assistant-display-name" maxLength={40} value={assistantName} onChange={(event) => setAssistantName(event.target.value)} /><label htmlFor="assistant-language">{translate(language, 'comfortableLanguage')}</label><select id="assistant-language" value={language.split('-')[0]} onChange={(event) => void choosePanelLanguage(event.target.value as Locale)}><option value="te">తెలుగు</option><option value="en">English</option><option value="hi">हिन्दी</option><option value="ta">தமிழ்</option><option value="kn">ಕನ್ನಡ</option><option value="ml">മലയാളം</option><option value="mr">मराठी</option></select></section>}
      <div className="dock-history" aria-live="polite">{session?.history?.length ? session.history.slice(-8).map((turn, index) => <p className={`chat-turn ${turn.role}`} key={`${index}-${turn.role}`}><strong>{turn.role === 'farmer' ? t.question : assistantName.trim() || t.appName}:</strong> {turn.text}</p>) : <p className="assistant-panel-intro">{t.general}</p>}</div>
      {answerAudio && <div className="dock-playback"><button type="button" onClick={togglePlayback}>{playing ? t.stop : translate(language, 'playAnswer')}</button></div>}
      <form className="dock-form" onSubmit={(event) => { event.preventDefault(); void submit(message); }}><input aria-label={t.typeQuestion} value={message} onChange={(event) => setMessage(event.target.value)} placeholder={t.typeQuestion} disabled={busy} /><button type="submit" disabled={busy || !message.trim()}>{busy ? t.loading : t.send}</button></form>
    </aside>}
  </>;
}
function FeaturePlaceholder() {
  const { language } = useVoiceSession();
  const { feature } = useParams();
  const location = useLocation();
  const state = location.state as { turn?: VoiceTurn; transcript?: string } | null;
  const item = featureRoutes.find((entry) => entry.path.slice(1) === feature);
  return <><Link to="/" className="back">← {translate(language,'askAnother')}</Link><p className="eyebrow">KISAN HITA</p><h1>{item?.label ?? translate(language,'feature')}</h1>
    {state?.turn ? <div className="route-result"><p className="route-action">{state.turn.result.clarification_required ? translate(language,'clarification') : translate(language,'openTool')}</p><p><strong>{translate(language,'question')}:</strong> “{state.transcript}”</p><p className="route-response">{assistantResponseForLanguage(state.turn.result.response, state.turn.result.response_language ?? state.turn.result.language, language)}</p>{state.turn.result.language_notice && <p className="feature-notice">{state.turn.result.language_notice}</p>}<p className="feature-notice">{state.turn.feature_notice}</p></div> : <p className="intro">{translate(language, 'general')}</p>}
    <div className="empty-state"><span className="empty-icon" aria-hidden="true">✳</span><p>{translate(language,'placeholderFeature')}</p></div></>;
}

function regionalCropNames(crops: string[], language: string) {
  const locale = language.toLowerCase().split('-')[0];
  const names: Record<string, Record<string, string>> = {
    en: { cotton:'cotton', rice:'rice', maize:'maize', greengram:'greengram', mango:'mango', sugarcane:'sugarcane', chillies:'chillies' },
    te: { cotton:'పత్తి', rice:'వరి', maize:'మొక్కజొన్న', greengram:'పెసలు', mango:'మామిడి', sugarcane:'చెరకు', chillies:'మిరప' },
    hi: { cotton:'कपास', rice:'धान', maize:'मक्का', greengram:'मूंग', mango:'आम', sugarcane:'गन्ना', chillies:'मिर्च' },
    ta: { cotton:'பருத்தி', rice:'நெல்', maize:'மக்காச்சோளம்', greengram:'பச்சைப்பயறு', mango:'மாம்பழம்', sugarcane:'கரும்பு', chillies:'மிளகாய்' },
    kn: { cotton:'ಹತ್ತಿ', rice:'ಭತ್ತ', maize:'ಮೆಕ್ಕೆಜೋಳ', greengram:'ಹೆಸರುಕಾಳು', mango:'ಮಾವು', sugarcane:'ಕಬ್ಬು', chillies:'ಮೆಣಸಿನಕಾಯಿ' },
    ml: { cotton:'പരുത്തി', rice:'നെല്ല്', maize:'ചോളം', greengram:'ചെറുപയർ', mango:'മാവ്', sugarcane:'കരിമ്പ്', chillies:'മുളക്' },
    mr: { cotton:'कापूस', rice:'भात', maize:'मका', greengram:'मूग', mango:'आंबा', sugarcane:'ऊस', chillies:'मिरची' },
  };
  const dictionary = names[locale] ?? names.en;
  return crops.map((crop) => dictionary[crop.toLowerCase()] ?? localizeCropName(crop, language)).join(', ');
}

function ChooseMyCrop() {
  const { language, session, setSession } = useVoiceSession();
  const routeState = useLocation().state as { transcript?: string; answer?: string; turn?: VoiceTurn } | null;
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  const [state, setState] = useState(session?.crop_details?.state ?? session?.farm_location?.state ?? '');
  const [district, setDistrict] = useState(session?.crop_details?.district ?? session?.farm_location?.district ?? '');
  const [soil, setSoil] = useState(session?.crop_details?.soil_type ?? 'unknown');
  const [water, setWater] = useState<'rainfed' | 'limited' | 'assured' | ''>(session?.crop_details?.water_availability ?? '');
  const [season, setSeason] = useState(session?.crop_details?.season ?? '');
  const [priority, setPriority] = useState(session?.crop_details?.priority ?? '');
  const [farmSize, setFarmSize] = useState(session?.crop_details?.farm_size_acres === undefined ? '' : String(session.crop_details.farm_size_acres));
  const [result, setResult] = useState<Awaited<ReturnType<typeof getCropRecommendations>> | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const size = farmSize ? Number(farmSize) : undefined;
    if (!stateByCanonicalName(state) || !districtByCanonicalName(state, district) || !season.trim()) { setError(translate(language,'cropRequired')); return; }
    if (size !== undefined && (!Number.isFinite(size) || size <= 0 || size > 100000)) { setError(t.cropTryAgain); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      const args = { state: state.trim() || undefined, district: district.trim(), soil_type: soil === 'unknown' ? undefined : soil, water_availability: water || undefined, farm_size_acres: size, season: season.trim(), priority: priority.trim() || undefined };
      const message = routeState?.transcript || translate(language,'sampleCrop');
      const answer = await runAgentTurn(session, language, message, args);
      setSession({ ...answer.session, crop_details: args });
      const details = answer.turn.result.tool_result;
      const recommendations = Array.isArray(details?.recommendations) ? details.recommendations as CropResponse['recommendations'] : [];
      const regionalContext = details?.regional_context as CropResponse['regional_context'];
      const outcome = details?.outcome === 'verified_recommendation' || details?.outcome === 'regional_context_only' || details?.outcome === 'no_applicable_evidence'
        ? details.outcome : recommendations.length ? 'verified_recommendation' : regionalContext ? 'regional_context_only' : 'no_applicable_evidence';
      setResult({
        recommendations: outcome === 'verified_recommendation' ? recommendations : [],
        disclaimer: answer.turn.result.response,
        source: String(details?.source ?? ''), is_mock: false, outcome,
        recommendation_ready: outcome === 'verified_recommendation' && recommendations.length > 0,
        missing_details: Array.isArray(details?.missing_information) ? details.missing_information as string[] : [],
        missing_conditions: Array.isArray(details?.missing_conditions) ? details.missing_conditions as string[] : [],
        evidence_issue: details?.evidence_issue as CropResponse['evidence_issue'],
        evidence: Array.isArray(details?.evidence) ? details.evidence as CropResponse['evidence'] : [],
        catalog_version: typeof details?.catalog_version === 'string' ? details.catalog_version : undefined,
        regional_context: regionalContext,
      });
    }
    catch { setError(t.offline); }
    finally { setBusy(false); }
  }
  return <section className="feature-workflow"><p className="eyebrow">KISAN HITA</p><h1>{t.crops}</h1><p className="intro">{t.cropMissing}</p>{routeState?.transcript&&<div className="route-result"><p><strong>{t.question}:</strong> “{routeState.transcript}”</p><p>{routeState.answer ?? (routeState.turn ? assistantResponseForLanguage(routeState.turn.result.response, routeState.turn.result.response_language ?? routeState.turn.result.language, language) : '')}</p></div>}
    <form className="workflow-form" onSubmit={submit}>
      <GeographicSelector idPrefix="crop" language={language} state={state} district={district} onStateChange={(value) => { setState(value); setDistrict(''); }} onDistrictChange={setDistrict} />
      <label htmlFor="crop-soil">{t.soil}</label><select id="crop-soil" value={soil} onChange={(event) => setSoil(event.target.value)}><option value="unknown">{t.unknown}</option>{([{value:'Black soil',key:'soilBlack'},{value:'Red soil',key:'soilRed'},{value:'Sandy soil',key:'soilSandy'},{value:'Clay soil',key:'soilClay'},{value:'Loamy soil',key:'soilLoamy'}] as const).map(({value,key}) => <option key={value} value={value}>{translate(language,key)}</option>)}</select>
      <label htmlFor="crop-water">{t.water}</label><select id="crop-water" value={water} onChange={(event) => setWater(event.target.value as typeof water)}><option value="">{t.unknown}</option><option value="rainfed">{t.rainfed}</option><option value="limited">{t.limited}</option><option value="assured">{t.assured}</option></select>
      <label htmlFor="crop-season">{t.season}</label><input id="crop-season" required maxLength={80} value={season} onChange={(event) => setSeason(event.target.value)} placeholder={translate(language,'cropSeasonExample')} />
      <label htmlFor="crop-priority">{t.priority}</label><input id="crop-priority" maxLength={100} value={priority} onChange={(event) => setPriority(event.target.value)} placeholder={translate(language,'cropPriorityExample')} />
      <label htmlFor="crop-size">{t.farmSize}</label><input id="crop-size" value={farmSize} onChange={(event)=>setFarmSize(event.target.value)} type="number" min="0.01" max="100000" step="0.01" placeholder={t.acres} />
      <button type="submit" disabled={busy}>{busy ? t.loading : t.getAdvice}</button>
    </form>
    {error && <p role="alert" className="farm-error">{error}</p>}
    {result && <section className="workflow-result" aria-live="polite">
      <p>{result.disclaimer}</p>
      {result.outcome === 'verified_recommendation' && result.recommendations.map((item) => <article key={item.crop}><h2>{localizeCropName(item.crop, language)}</h2><p>{item.reasons.join(' ')}</p>{item.cultivation_notes.map((note,index)=><p key={index}>{note}</p>)}</article>)}
      {result.regional_context && <article>
        <h2>{translate(language,'cropRegionHeading')}</h2><h3>{translate(language,'cropRegionCrops')}</h3>
        <p>{regionalCropNames(result.regional_context.crops_reported, language)}</p>
        <p>{translate(language,'cropRegionWarning')}</p>
        <p>{translate(language,'cropRegionNext')}</p>
        <a href={result.regional_context.source_url} target="_blank" rel="noreferrer">{result.evidence?.find((item) => item.evidence_type === 'regional_context')?.source_title ?? result.regional_context.source}</a>
        <p>{translate(language,'cropPublishedLabel')}: {result.regional_context.publication_year ?? result.evidence?.find((item) => item.evidence_type === 'regional_context')?.publication_year ?? translate(language,'unknown')}</p>
      </article>}
      {!!result.evidence?.filter((item) => item.evidence_type !== 'regional_context').length && <section className="crop-evidence" aria-label={translate(language,'cropEvidenceLabel')}>
        <h2>{translate(language,'cropEvidenceLabel')}</h2>
        {result.evidence.filter((item) => item.evidence_type !== 'regional_context').map((item) => <article key={item.evidence_id}>
          <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_title}</a>
          <p>{item.publisher}</p>
          <p>{translate(language,'cropPublishedLabel')}: {item.publication_date ?? item.publication_year ?? translate(language,'unknown')}</p>
          {item.reviewed_on && <p>{translate(language,'cropReviewedLabel')}: {item.reviewed_on}</p>}
          {(item.valid_from || item.valid_until) && <p>{translate(language,'cropEffectiveLabel')}: {[item.valid_from, item.valid_until].filter(Boolean).join(' - ')}</p>}
          <p>{translate(language,'cropAppliesLabel')}: {item.geography}</p>
          {item.season && <p>{translate(language,'cropSeasonLabel')}: {translate(language, item.season.toLowerCase() === 'kharif' ? 'seasonKharif' : item.season.toLowerCase() === 'rabi' ? 'seasonRabi' : item.season.toLowerCase() === 'zaid' ? 'seasonZaid' : 'seasonOther')}</p>}
          {item.conditions.length > 0 && <p>{translate(language,'cropConditionsLabel')}: {item.conditions.join('; ')}</p>}
          {item.reference_period && <p>{translate(language,'cropReferencePeriodLabel')}: {item.reference_period}</p>}
        </article>)}
      </section>}
    </section>}
  </section>;
}

function CheckMyCrop() {
  const { language, session, setSession } = useVoiceSession();
  const routeState = useLocation().state as { transcript?: string; answer?: string; turn?: VoiceTurn } | null;
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  const [file, setFile] = useState<File | null>(null);
  const [crop, setCrop] = useState(''); const [symptoms, setSymptoms] = useState('');
  const [affected, setAffected] = useState(''); const [pattern, setPattern] = useState(''); const [started, setStarted] = useState(''); const [recentChanges, setRecentChanges] = useState('');
  const [result, setResult] = useState<Awaited<ReturnType<typeof sendCropPhoto>> | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const preview = useMemo(() => file && typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : '', [file]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const details = [affected && `${translate(language,'affectedPart')} ${translate(language,affected as keyof typeof messages.en)}`, pattern && `${translate(language,'symptomPattern')} ${translate(language,pattern as keyof typeof messages.en)}`, started && `${translate(language,'startedWhen')} ${translate(language,started as keyof typeof messages.en)}`, recentChanges && `${translate(language,'recentChanges')} ${recentChanges}`, symptoms].filter(Boolean).join('. ');
    if (!file && !details.trim()) { setError(translate(language,'cropTryAgain')); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      const active = session ?? await createVoiceConversation(language);
      if (!session) setSession(active);
      if (!file) {
        const note = `${crop ? `${crop}: ` : ''}${details}`;
        const answer = `${translate(language,'cropRecordOnly')} ${translate(language,'cropUrgent')}`;
        setResult({ possible_conditions: [], guidance: [answer], needs_expert: true, uncertainty: translate(language,'cropRecordOnly'), source: 'Symptom-guided intake only; no diagnostic model.', is_mock: false, agent_answer: answer });
        setSession({ ...active, history: [...(active.history ?? []), { role: 'farmer', text: note }, { role: 'assistant', text: answer }] });
        return;
      }
      const next = await sendCropPhoto(file, { crop, symptoms: details, language, conversationId: active.conversation_id });
      setResult(next);
      if (next.agent_answer) setSession({ ...active, history: [...(active.history ?? []), { role: 'farmer', text: `${translate(language,'transcriptSent')} ${t.cropName}: ${crop || translate(language,'cropNotGiven')}. ${t.symptoms}: ${details || translate(language,'cropNotGiven')}.` }, { role: 'assistant', text: next.agent_answer }] });
    }
    catch (cause) { setError(localizedApiError(cause, language, '/crop-health/analyze')); }
    finally { setBusy(false); }
  }
  return <section className="feature-workflow"><p className="eyebrow">KISAN HITA</p><h1>{t.checkCrop}</h1><p className="intro">{t.imageNoModel} {translate(language,'photoLimit')}</p>{routeState?.transcript&&<div className="route-result"><p><strong>{t.question}:</strong> “{routeState.transcript}”</p><p>{routeState.answer ?? (routeState.turn ? assistantResponseForLanguage(routeState.turn.result.response, routeState.turn.result.response_language ?? routeState.turn.result.language, language) : '')}</p></div>}
    <form className="workflow-form" onSubmit={submit}>
      <label htmlFor="crop-photo">{t.photo}</label><input id="crop-photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setResult(null); }} />
      {file && <img className="crop-photo-preview" src={preview} alt={translate(language,'cropPhotoAlt')} />}
      <label htmlFor="crop-name">{t.cropName}</label><input id="crop-name" value={crop} onChange={(event) => setCrop(event.target.value)} maxLength={100} />
      <label htmlFor="crop-affected">{translate(language,'affectedPart')}</label><select id="crop-affected" value={affected} onChange={(event)=>setAffected(event.target.value)}><option value="">{t.unknown}</option>{(['affectedLeaves','affectedStem','affectedFruit','affectedWhole'] as const).map(key=><option value={key} key={key}>{translate(language,key)}</option>)}</select>
      <label htmlFor="crop-pattern">{translate(language,'symptomPattern')}</label><select id="crop-pattern" value={pattern} onChange={(event)=>setPattern(event.target.value)}><option value="">{t.unknown}</option>{(['symptomSpots','symptomYellow','symptomWilting','symptomHoles','symptomGrowth','symptomOther'] as const).map(key=><option value={key} key={key}>{translate(language,key)}</option>)}</select>
      <label htmlFor="crop-started">{translate(language,'startedWhen')}</label><select id="crop-started" value={started} onChange={(event)=>setStarted(event.target.value)}><option value="">{t.unknown}</option>{(['symptomStartToday','symptomStartFewDays','symptomStartWeek','symptomStartLong'] as const).map(key=><option value={key} key={key}>{translate(language,key)}</option>)}</select>
      <label htmlFor="crop-recent">{translate(language,'recentChanges')}</label><input id="crop-recent" value={recentChanges} onChange={(event)=>setRecentChanges(event.target.value)} maxLength={300} />
      <label htmlFor="crop-symptoms">{t.symptoms}</label><textarea id="crop-symptoms" value={symptoms} onChange={(event) => setSymptoms(event.target.value)} maxLength={1000} rows={4} placeholder={translate(language,'cropSymptomsExample')} />
      <button type="submit" disabled={busy}>{busy ? t.loading : file ? t.checkPhoto : t.send}</button>
    </form>
    {error && <p role="alert" className="farm-error">{error}</p>}
    {result && <section className="workflow-result" role="status"><h2>{result.agent_answer ?? (file ? t.imageNoModel : translate(language,'cropRecordOnly'))}</h2><p>{t.expertHelp}</p>{result.guidance.filter((guidance) => guidance !== result.agent_answer).map((guidance,index)=><p key={index}>{guidance}</p>)}</section>}
  </section>;
}

function marketMessageWithoutDemoLabels(message: string): string {
  return message.split(/(?<=[.!?])\s+/)
    .filter((sentence) => !(/\b(?:demo|sample).*\b(?:record|not live)\b/i.test(sentence) || /\bnot live market data\b/i.test(sentence)))
    .join(' ').trim();
}

function MarketPrices() {
  const { language, session, setSession } = useVoiceSession();
  const routeState = useLocation().state as { transcript?: string; answer?: string; turn?: VoiceTurn } | null;
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  const [crop, setCrop] = useState(''); const [market, setMarket] = useState(''); const [variety, setVariety] = useState('');
  const [state, setState] = useState(''); const [district, setDistrict] = useState('');
  const [result, setResult] = useState<Awaited<ReturnType<typeof getMarketPrices>> | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setResult(null);
    try {
      if (!stateByCanonicalName(state) || !districtByCanonicalName(state, district)) { setError(translate(language,'weatherLocationRequired')); return; }
      const args = { crop, market, variety: variety || undefined, state, district };
      const answer = await runAgentTurn(session, language, routeState?.transcript || translate(language,'samplePrice'), args);
      setSession(answer.session);
      const tool = answer.turn.result.tool_result;
      const prices = Array.isArray(tool?.prices) ? tool.prices as MarketLookupResponse['prices'] : [];
      setResult({ prices, available: prices.length > 0, message: answer.turn.result.response, source: String(tool?.source ?? 'No verified data') });
    }
    catch { setError(t.offline); }
    finally { setBusy(false); }
  }
  return <section className="feature-workflow"><p className="eyebrow">KISAN HITA</p><h1>{t.prices}</h1><p className="intro">{translate(language,'marketIntro')}</p>{routeState?.transcript&&<div className="route-result"><p><strong>{t.question}:</strong> “{routeState.transcript}”</p><p>{routeState.answer ?? (routeState.turn ? assistantResponseForLanguage(routeState.turn.result.response, routeState.turn.result.response_language ?? routeState.turn.result.language, language) : '')}</p></div>}
    <form className="workflow-form" onSubmit={submit}><label htmlFor="market-crop">{t.commodity}</label><input id="market-crop" required maxLength={100} value={crop} onChange={(event) => setCrop(event.target.value)} /><GeographicSelector idPrefix="market" language={language} state={state} district={district} onStateChange={(value) => { setState(value); setDistrict(''); }} onDistrictChange={setDistrict} /><label htmlFor="market-town">{t.market}</label><input id="market-town" required maxLength={160} value={market} onChange={(event) => setMarket(event.target.value)} /><label htmlFor="market-variety">{t.variety}</label><input id="market-variety" value={variety} onChange={(event) => setVariety(event.target.value)} maxLength={100} /><button type="submit" disabled={busy}>{busy ? t.loading : t.checkPrices}</button></form>
    {error && <p role="alert" className="farm-error">{error}</p>}{result && <section className="workflow-result" role="status">{result.prices.length === 0 && marketMessageWithoutDemoLabels(result.message) && <p>{marketMessageWithoutDemoLabels(result.message)}</p>}{result.prices.map((record,index)=><article key={`${record.market}-${record.observed_at}-${index}`}><h2>{localizeCropName(record.crop, language)} — {record.market}</h2>{record.is_stale&&<p>{translate(language,'marketStale')}</p>}<p>{translate(language,'priceLabel')}: {record.price} {record.unit}</p>{record.minimum_price!=null&&<p>{translate(language,'minimum')}: {record.minimum_price} {record.unit}</p>}{record.maximum_price!=null&&<p>{translate(language,'maximum')}: {record.maximum_price} {record.unit}</p>}{record.modal_price!=null&&<p>{translate(language,'modal')}: {record.modal_price} {record.unit}</p>}<p>{translate(language,'priceDate')}: {new Date(record.observed_at).toLocaleDateString(language)}</p></article>)}</section>}
  </section>;
}

function AskKisanHita() {
  const { language, session, assistantName } = useVoiceSession();
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  return <section className="feature-workflow"><p className="eyebrow">KISAN HITA</p><h1>{t.ask}</h1><p className="intro">{t.general}</p><div className="chat-history" aria-live="polite">{(session?.history ?? []).map((turn, index) => <p className={`chat-turn ${turn.role}`} key={`${index}-${turn.role}`}><strong>{turn.role === 'farmer' ? t.question : assistantName.trim() || t.appName}:</strong> {turn.text}</p>)}</div><p className="feature-notice">{translate(language,'openAssistant')}</p></section>;
}

export function GeographicSelector({ idPrefix, language, state, district, onStateChange, onDistrictChange }: { idPrefix: string; language: string; state: string; district: string; onStateChange: (value: string) => void; onDistrictChange: (value: string) => void }) {
  const locale = language.toLowerCase().split('-')[0] as Locale;
  const t = messages[locale] ?? messages.en;
  const selectedState = stateByCanonicalName(state);
  const districts = districtsForStateCode(selectedState?.lgdCode);
  const validSavedDistrict = districts.some((item) => item.name === district);
  return <>
    <label htmlFor={`${idPrefix}-state`}>{t.state}</label>
    <select id={`${idPrefix}-state`} value={stateByCanonicalName(state)?.name ?? ''} required onChange={(event) => { onStateChange(event.target.value); onDistrictChange(''); }}>
      <option value="">{t.chooseState}</option>{indianGeography.map((item) => <option key={item.lgdCode} value={item.name}>{localizeKnownLocation(item.name, language)}</option>)}
    </select>
    <label htmlFor={`${idPrefix}-district`}>{t.district}</label>
    <select id={`${idPrefix}-district`} value={validSavedDistrict ? district : ''} required={!selectedState || districts.length > 0} disabled={!selectedState || districts.length === 0} onChange={(event) => onDistrictChange(event.target.value)}>
      <option value="">{!selectedState ? t.selectStateFirst : districts.length ? t.chooseDistrict : t.noDistrictsAvailable}</option>
      {!validSavedDistrict && district && stateByCanonicalName(state) && <option value="" disabled>{`${localizeKnownLocation(district, language)} — ${t.savedLocationNeedsUpdate}`}</option>}
      {districts.map((item) => <option key={item.lgdCode} value={item.name}>{geographicDisplayName(item, language)}</option>)}
    </select>
    {!validSavedDistrict && district && stateByCanonicalName(state) && <small className="feature-notice" role="status">{t.savedLocationNeedsUpdate}</small>}
  </>;
}

function simpleWeatherSummary(summary: string, language: string) {
  const exact: Record<string, Parameters<typeof translate>[1]> = {
    'clear':'weatherSummaryClear', 'clear sky':'weatherSummaryClear',
    'mostly clear to partly cloudy':'weatherSummaryClouds', 'partly cloudy':'weatherSummaryClouds',
    'overcast':'weatherSummaryCloudy', 'fog':'weatherSummaryFog', 'drizzle':'weatherSummaryLightRain',
    'rain':'weatherSummaryRain', 'rain showers':'weatherSummaryShowers', 'snow':'weatherSummarySnow',
    'snow showers':'weatherSummarySnow', 'thunderstorm':'weatherSummaryStorm',
    'weather summary unavailable':'weatherSummaryUnavailable',
  };
  const key = exact[summary.trim().toLowerCase()];
  if (key) return translate(language, key);
  return language.toLowerCase().startsWith('en') ? summary : `${translate(language, 'sourceTextInEnglish')} ${summary}`;
}

function simpleFarmAdvice(note: string, language: string) {
  const exact: Record<string, Parameters<typeof translate>[1]> = {
    'Rain is possible in the next few days. Check drainage and local field conditions; consider this forecast before irrigation or field work.':'farmAdviceRain',
    'No major rain signal appears in this model forecast. Verify conditions locally before making irrigation or field-work decisions.':'farmAdviceDry',
    'Wind may be strong. Check conditions at the field before work that can be affected by wind.':'farmAdviceWind',
    'A weather forecast alone cannot establish whether spraying is safe. Check the product label and local guidance.':'farmAdviceSprayUnknown',
    'The forecast cannot confirm product-specific spray safety. Check the label’s wind and rain restrictions and consult a local agricultural adviser.':'farmAdviceProductUnknown',
  };
  const key = exact[note];
  if (key) return translate(language, key);
  return language.toLowerCase().startsWith('en') ? note : `${translate(language, 'sourceTextInEnglish')} ${note}`;
}

function MyFarmToday() {
  const locationState = useLocation();
  const routeState = locationState.state as { turn?: VoiceTurn; transcript?: string; answer?: string } | null;
  const { session, setSession, language } = useVoiceSession();
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  const [state, setState] = useState(session?.farm_location?.state ?? '');
  const [district, setDistrict] = useState(session?.farm_location?.district ?? '');
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [farm, setFarm] = useState<FarmTodayResponse | null>(null);
  const [directAnswer, setDirectAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [geoMessage, setGeoMessage] = useState('');
  const [crop, setCrop] = useState('');
  const [growthStage, setGrowthStage] = useState('');
  const [sprayProduct, setSprayProduct] = useState('');
  const question = routeState?.transcript ?? '';
  const autoLoaded = useRef('');

  useEffect(() => {
    if (session?.farm_location) {
      setState(stateByCanonicalName(session.farm_location.state)?.name ?? session.farm_location.state);
      setDistrict(session.farm_location.district);
    }
  }, [session?.farm_location?.state, session?.farm_location?.district]);

  async function loadFarmToday(nextState = state, nextDistrict = district, position = coords) {
    if (!stateByCanonicalName(nextState) || !districtByCanonicalName(nextState, nextDistrict)) { setError(translate(language,'weatherLocationRequired')); return; }
    setLoading(true); setError(''); setFarm(null);
    try {
      let active = session ?? await createVoiceConversation(language);
      const selected = { state: nextState, district: nextDistrict.trim() };
      active = await saveFarmLocation(active.conversation_id, selected);
      setSession(active);
      if (question) {
        const answer = await askAssistant({ conversation_id: active.conversation_id, language, message: question,
          context: { continue_pending: true, tool_arguments: { ...(position ?? {}) } } });
        const displayResponse = assistantResponseForLanguage(answer.response, answer.response_language ?? answer.language, language);
        setDirectAnswer(displayResponse);
        const forecastData = answer.tool_result?.forecast_data;
        if (forecastData && typeof forecastData === 'object') setFarm(forecastData as FarmTodayResponse);
        setSession({ ...active, history: [...(active.history ?? []), { role: 'assistant', text: displayResponse }] });
        if (!forecastData) setError(displayResponse);
        return;
      }
      const result = await getFarmToday({ ...selected, ...(position ?? {}), question: question || undefined, language });
      if (result.is_mock) { setError(translate(language,'weatherUnavailable')); return; }
      setDirectAnswer('');
      setFarm(result);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message.toLowerCase() : '';
      setError(message.includes('matching') || message.includes('selected state') ? translate(language,'placeNotFound') : translate(language,'weatherRetry'));
    } finally { setLoading(false); }
  }

  async function submitFarmDetails(event: FormEvent) {
    event.preventDefault();
    if (!crop.trim() || !growthStage.trim() || !sprayProduct.trim()) return;
    setLoading(true); setError('');
    try {
      if (question && session) {
        const answer = await askAssistant({ conversation_id: session.conversation_id, language, message: question,
          context: { continue_pending: true, tool_arguments: { ...(coords ?? {}), crop: crop.trim(), growth_stage: growthStage.trim(), spray_product: sprayProduct.trim() } } });
        const displayResponse = assistantResponseForLanguage(answer.response, answer.response_language ?? answer.language, language);
        setDirectAnswer(displayResponse);
        const forecastData = answer.tool_result?.forecast_data;
        if (forecastData && typeof forecastData === 'object') setFarm(forecastData as FarmTodayResponse);
        setSession({ ...session, history: [...(session.history ?? []), { role: 'assistant', text: displayResponse }] });
        if (!forecastData) setError(displayResponse);
        return;
      }
      const result = await getFarmToday({ state, district, ...(coords ?? {}), question: question || undefined,
        crop: crop.trim(), growth_stage: growthStage.trim(), spray_product: sprayProduct.trim(), language });
      if (result.is_mock) { setError(translate(language,'weatherUnavailable')); return; }
      setFarm(result);
    } catch { setError(translate(language,'detailsRetry')); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    const storedForecast = routeState?.turn?.result.tool_result?.forecast_data;
    if (storedForecast && typeof storedForecast === 'object') {
      setFarm(storedForecast as FarmTodayResponse);
      setDirectAnswer(routeState?.turn ? assistantResponseForLanguage(routeState.turn.result.response, routeState.turn.result.response_language ?? routeState.turn.result.language, language) : routeState?.answer ?? '');
      autoLoaded.current = question;
      return;
    }
    if (!question || autoLoaded.current === question || !session?.farm_location || !districtByCanonicalName(session.farm_location.state, session.farm_location.district)) return;
    autoLoaded.current = question;
    void loadFarmToday(session.farm_location.state, session.farm_location.district, null);
  }, [question, session?.farm_location?.state, session?.farm_location?.district]);

  function useDeviceLocation() {
    setGeoMessage('');
    if (!navigator.geolocation) { setGeoMessage(translate(language,'geolocationFallback')); return; }
    navigator.geolocation.getCurrentPosition(
      ({ coords: position }) => { setCoords({ latitude: position.latitude, longitude: position.longitude }); setGeoMessage(translate(language,'geoFound')); },
      () => setGeoMessage(translate(language,'geoDenied')),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  async function speakWeather() {
    if (!farm) return;
    const details = [
      farm.current?.temperature_c != null ? `${farm.current.temperature_c} degrees Celsius` : '',
      ...farm.advice.map((note) => simpleFarmAdvice(note,language)),
    ].filter(Boolean);
    const text = directAnswer || `${farm.district}, ${farm.state}. ${details.join(' ')}`;
    try {
      const active = session ?? await createVoiceConversation(language);
      if (!session) setSession(active);
      const speech = await synthesizeVoice(active.conversation_id, text);
      if (!speech.available || speech.is_mock || !speech.audio_base64) { setGeoMessage(translate(language, 'ttsUnavailable')); return; }
      const bytes = Uint8Array.from(atob(speech.audio_base64), (character) => character.charCodeAt(0));
      const audio = new Audio(URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' })));
      try { await audio.play(); setGeoMessage(translate(language, 'playingAnswer')); }
      catch { setGeoMessage(translate(language, 'playbackError')); }
    } catch { setGeoMessage(translate(language, 'ttsUnavailable')); }
  }

  return <section className="farm-today">
    <Link to="/" className="back">← {translate(language,'askAnother')}</Link>
    <p className="eyebrow">KISAN HITA</p>
    <h1>{t.weather}</h1>
    {question && <div className="route-result"><p><strong>{t.question}:</strong> “{question}”</p>{directAnswer ? <p className="route-response">{directAnswer}</p> : (routeState?.answer ?? routeState?.turn?.result.response) && <p className="route-response">{routeState?.answer ?? (routeState?.turn ? assistantResponseForLanguage(routeState.turn.result.response, routeState.turn.result.response_language ?? routeState.turn.result.language, language) : '')}</p>}</div>}
    <p className="intro">{t.locationPrompt}</p>
    <form className="farm-location-form" onSubmit={(event) => { event.preventDefault(); void loadFarmToday(); }}>
      <GeographicSelector idPrefix="farm" language={language} state={state} district={district} onStateChange={(value) => { setState(value); setDistrict(''); setFarm(null); setCoords(null); }} onDistrictChange={(value) => { setDistrict(value); setFarm(null); setCoords(null); }} />
      <div className="farm-location-actions"><button type="button" className="secondary-button" onClick={useDeviceLocation}>{t.useLocation}</button><button type="submit" disabled={loading || !state || !district.trim()}>{loading ? t.loading : t.getWeather}</button></div>
      {geoMessage && <p className="feature-notice" role="status">{geoMessage}</p>}
    </form>
    {error && <p className="farm-error" role="alert">{error}</p>}
    {farm && <div className="farm-results" aria-live="polite">
      <div className="farm-heading"><div><p className="eyebrow">{translate(language,'yourLocation')}</p><h2>{localizeKnownLocation(farm.district ?? '',language)}, {localizeKnownLocation(farm.state ?? '',language)}</h2><p>{translate(language,'weatherNear')} {localizeKnownLocation(farm.resolved_place ?? farm.location ?? '',language)}. {translate(language,'fieldDifference')}</p></div><button type="button" className="secondary-button" onClick={() => { setFarm(null); setError(''); }}>{t.changeLocation}</button></div>
      {farm.is_stale && <p className="farm-warning" role="alert">{translate(language,'staleWeather')}</p>}
      {(farm.current?.temperature_c != null || farm.current?.precipitation_mm != null || farm.current?.relative_humidity_percent != null || farm.current?.wind_speed_kmh != null) && <div className="current-weather">
        {farm.current?.temperature_c != null && <div><span>{translate(language,'temperature')}</span><strong>{farm.current.temperature_c}°C</strong></div>}
        {farm.current?.precipitation_mm != null && <div><span>{translate(language,'rain')}</span><strong>{farm.current.precipitation_mm} mm</strong></div>}
        {farm.current?.relative_humidity_percent != null && <div><span>{translate(language,'humidity')}</span><strong>{farm.current.relative_humidity_percent}%</strong></div>}
        {farm.current?.wind_speed_kmh != null && <div><span>{translate(language,'wind')}</span><strong>{farm.current.wind_speed_kmh} km/h</strong></div>}
      </div>}
      <div className="farm-heading"><div><h2>{t.nextDays.replace('7', String((farm.forecast ?? []).length)).replace('days', (farm.forecast ?? []).length === 1 ? 'day' : 'days')}</h2></div>{farm.fetched_at && <span>{translate(language,'checkedAt')} {new Date(farm.fetched_at).toLocaleTimeString(language, { hour: 'numeric', minute: '2-digit' })}</span>}</div>
      {(farm.forecast ?? []).length > 0 ? <div className="forecast-list">{farm.forecast.map((day) => <article className="forecast-day" key={day.date}>
        <div><strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString(language, { weekday: 'short', month: 'short', day: 'numeric' })}</strong><span>{simpleWeatherSummary(day.summary,language)}</span></div>
        {(day.temperature_min_c != null || day.temperature_c != null) && <div><strong>{day.temperature_min_c != null && day.temperature_c != null ? `${day.temperature_min_c}° to ${day.temperature_c}°C` : `${day.temperature_c ?? day.temperature_min_c}°C`}</strong><span>{translate(language,'temperature')}</span></div>}
        {day.precipitation_probability != null && <div><strong>{day.precipitation_probability}%</strong><span>{translate(language,'chanceRain')}</span></div>}
        {day.precipitation_mm != null && <div><strong>{day.precipitation_mm} mm</strong><span>{translate(language,'expectedRain')}</span></div>}
      </article>)}</div> : <p>{translate(language,'noForecast')}</p>}
      <section className="farm-advice"><h2>{t.know}</h2>{(farm.advice ?? []).map((note, index) => <p key={index}>{simpleFarmAdvice(note,language)}</p>)}{farm.clarification_required && farm.follow_up_question && <><p className="follow-up"><strong>{translate(language,'oneQuestion')}</strong> {farm.follow_up_question === 'Which crop, growth stage, and spray product are you asking about?' ? translate(language,'weatherFollowUpQuestion') : language.toLowerCase().startsWith('en') ? farm.follow_up_question : `${translate(language,'sourceTextInEnglish')} ${farm.follow_up_question}`}</p><form className="farm-followup" onSubmit={submitFarmDetails}><label htmlFor="farm-crop">{translate(language,'whichCrop')}</label><input id="farm-crop" value={crop} onChange={(event) => setCrop(event.target.value)} required maxLength={100}/><label htmlFor="farm-stage">{translate(language,'growthStage')}</label><input id="farm-stage" value={growthStage} onChange={(event) => setGrowthStage(event.target.value)} required maxLength={100} placeholder={translate(language,'cropStageExample')}/><label htmlFor="farm-spray">{translate(language,'sprayProduct')}</label><input id="farm-spray" value={sprayProduct} onChange={(event) => setSprayProduct(event.target.value)} required maxLength={160}/><button type="submit" disabled={loading}>{loading ? t.loading : t.send}</button></form></>}</section>
      <section className="farm-alerts"><h2>{t.alerts}</h2>{farm.warnings_available && farm.alerts?.length ? <ul>{farm.alerts.map((alert, index) => <li key={index}>{language.toLowerCase().startsWith('en') ? alert : `${translate(language,'sourceTextInEnglish')} ${alert}`}</li>)}</ul> : <p className="small-note">{translate(language,'officialAlertsMissing')}</p>}<a href="https://mausam.imd.gov.in/" target="_blank" rel="noreferrer">{translate(language,'checkImd')}</a></section>
      <p className="weather-attribution">{translate(language,'weatherBy')} <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a></p>
      <button type="button" className="secondary-button listen-weather" onClick={speakWeather}>{t.listenWeather}</button>
    </div>}
    {!farm && !loading && !error && <div className="empty-state"><span className="empty-icon" aria-hidden="true">☀</span><p>{t.noWeather}</p></div>}
  </section>;
}

export function App() {
  return <BrowserRouter><VoiceSessionProvider><Routes><Route element={<AppLayout />}><Route index element={<VoiceHome />} /><Route path="my-farm-today" element={<MyFarmToday />} /><Route path="choose-my-crop" element={<ChooseMyCrop />} /><Route path="check-my-crop" element={<CheckMyCrop />} /><Route path="market-prices" element={<MarketPrices />} /><Route path="ask-kisan-hita" element={<AskKisanHita />} /><Route path=":feature" element={<FeaturePlaceholder />} /><Route path="*" element={<VoiceHome />} /></Route></Routes></VoiceSessionProvider></BrowserRouter>;
}
