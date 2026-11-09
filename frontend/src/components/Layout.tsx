import { Link, NavLink, Outlet } from 'react-router-dom';
import type { FeatureKey } from '../types/api';
import type { Locale } from '../localization';
import { messages } from '../localization';

const features: Array<{ key: FeatureKey; label: string; path: string }> = [
  { key: 'my-farm-today', label: 'Weather', path: '/my-farm-today' },
  { key: 'choose-my-crop', label: 'Choose My Crop', path: '/choose-my-crop' },
  { key: 'check-my-crop', label: 'Check My Crop', path: '/check-my-crop' },
  { key: 'market-prices', label: 'Market Prices', path: '/market-prices' },
  { key: 'ask-kisan-hita', label: 'Ask Kisan Hita', path: '/ask-kisan-hita' },
];

export function Layout({ language = 'en', onLanguageChange }: { language?: Locale; onLanguageChange?: (language: Locale) => void }) {
  const t = messages[language.split('-')[0] as Locale] ?? messages.en;
  return <div className="app-shell"><header className="topbar"><Link className="brand" to="/">{t.appName}</Link><label className="global-language">{t.chooseLanguage}<select aria-label={t.chooseLanguage} value={language} onChange={(event) => onLanguageChange?.(event.target.value as Locale)}><option value="te">తెలుగు</option><option value="en">English</option><option value="hi">हिन्दी</option><option value="ta">தமிழ்</option><option value="kn">ಕನ್ನಡ</option><option value="ml">മലയാളം</option><option value="mr">मराठी</option></select></label></header><div className="content"><aside className="sidebar" aria-label={t.tools}><p className="nav-label">{t.tools}</p>{features.map((f) => <NavLink key={f.key} to={f.path} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>{t[f.key === 'my-farm-today' ? 'weather' : f.key === 'choose-my-crop' ? 'crops' : f.key === 'check-my-crop' ? 'checkCrop' : f.key === 'market-prices' ? 'prices' : 'ask']}</NavLink>)}</aside><main className="main"><Outlet /></main></div></div>;
}

export const featureRoutes = features;
