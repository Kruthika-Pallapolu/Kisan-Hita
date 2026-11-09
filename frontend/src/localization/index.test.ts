import { describe, expect, it } from 'vitest';
import { assistantResponseForLanguage, getLocalizationAudit, localizeCropName, localizeKnownLocation, messages, supportedLocales, translate, translationReviewStatus } from './index';

describe('localization status', () => {
  it('keeps a separate auditable record for all seven configured languages', () => {
    expect(supportedLocales).toEqual(['te', 'en', 'hi', 'ta', 'kn', 'ml', 'mr']);
    for (const language of supportedLocales) {
      const audit = getLocalizationAudit(language);
      expect(audit.supported).toBe(true);
      expect(audit.total).toBeGreaterThan(0);
      expect(audit.percentage).toBe(100);
      expect(audit.untranslatedKeys).toEqual([]);
      if (language !== 'en') expect(audit.intentionalUnchangedKeys).toContain('appName');
      expect(audit.untranslatedKeys.length).toBe(audit.total - audit.translated);
      expect(translationReviewStatus[language]).toBe(language === 'en' ? 'source-language' : 'fluent-speaker-review-required');
    }
  });

  it('marks unsupported locales and provides a deterministic English fallback', () => {
    const audit = getLocalizationAudit('xx-ZZ');
    expect(audit.supported).toBe(false);
    expect(audit.percentage).toBe(0);
    expect(translate('xx-ZZ', 'listen')).toBe(translate('en', 'listen'));
  });

  it('has reviewed translations for the core listening controls in every configured language', () => {
    const keys = ['listen', 'finish', 'cancel', 'stop', 'noVoice', 'emptySpeech'] as const;
    for (const language of supportedLocales.filter((code) => code !== 'en')) {
      const audit = getLocalizationAudit(language);
      for (const key of keys) expect(audit.untranslatedKeys, `${language}:${key}`).not.toContain(key);
    }
  });

  it('provides every audio journey label without an English catalog fallback', () => {
    const keys = ['recording', 'preparingAudio', 'transcribingAudio', 'reviewTranscript', 'audioUnavailable', 'audioError', 'playingAnswer', 'playAnswer', 'answerReady', 'playbackError'] as const;
    for (const language of supportedLocales.filter((code) => code !== 'en')) {
      const audit = getLocalizationAudit(language);
      for (const key of keys) {
        expect(audit.untranslatedKeys, `${language}:${key}`).not.toContain(key);
        expect(translate(language, key)).not.toBe(translate('en', key));
      }
    }
  });

  it('localizes known crop commodities and preserves unknown cultivar and API values', () => {
    const expected: Record<string, string> = {
      te:'పత్తి', en:'cotton', hi:'कपास', ta:'பருத்தி', kn:'ಹತ್ತಿ', ml:'പരുത്തി', mr:'कापूस',
    };
    for (const language of supportedLocales) expect(localizeCropName('Cotton', language)).toBe(expected[language]);
    expect(localizeCropName('Sona Masuri BPT 5204', 'te')).toBe('Sona Masuri BPT 5204');
    expect(localizeCropName('market-crop-id-17', 'mr')).toBe('market-crop-id-17');
  });

  it('localizes common market commodities across all seven locales and recognizes provider aliases', () => {
    const names: Record<string, Record<string, string>> = {
      wheat:{te:'గోధుమలు',en:'wheat',hi:'गेहूँ',ta:'கோதுமை',kn:'ಗೋಧಿ',ml:'ഗോതമ്പ്',mr:'गहू'},
      'green gram':{te:'పెసలు',en:'green gram',hi:'मूँग',ta:'பாசிப்பயறு',kn:'ಹೆಸರುಕಾಳು',ml:'ചെറുപയർ',mr:'मूग'},
      bajra:{te:'సజ్జలు',en:'pearl millet',hi:'बाजरा',ta:'கம்பு',kn:'ಸಜ್ಜೆ',ml:'കമ്പ്',mr:'बाजरी'},
      brinjal:{te:'వంకాయ',en:'brinjal',hi:'बैंगन',ta:'கத்தரிக்காய்',kn:'ಬದನೆಕಾಯಿ',ml:'വഴുതന',mr:'वांगी'},
      coconut:{te:'కొబ్బరి',en:'coconut',hi:'नारियल',ta:'தேங்காய்',kn:'ತೆಂಗಿನಕಾಯಿ',ml:'തേങ്ങ',mr:'नारळ'},
    };
    for (const [commodity, labels] of Object.entries(names)) {
      for (const locale of supportedLocales) expect(localizeCropName(commodity, locale), `${locale}:${commodity}`).toBe(labels[locale]);
    }
    expect(localizeCropName('Pearl Millet', 'kn')).toBe(names.bajra.kn);
    expect(localizeCropName('Eggplant', 'ta')).toBe(names.brinjal.ta);
    expect(localizeCropName('Red Gram (Tur)', 'mr')).toBe('तूर');
    expect(localizeCropName('Unlisted market commodity 204', 'kn')).toBe('Unlisted market commodity 204');
  });

  it('localizes known Warangal pilot locations while retaining unknown farmer-entered names', () => {
    expect(localizeKnownLocation('Telangana', 'te')).toBe('తెలంగాణ');
    expect(localizeKnownLocation('Warangal Urban', 'te')).toBe('వరంగల్ అర్బన్');
    expect(localizeKnownLocation('My Village', 'te')).toBe('My Village');
  });

  it('localizes every supported state and union territory without changing its canonical input value', () => {
    const states = ['Andhra Pradesh','Arunachal Pradesh','Assam','Bihar','Chhattisgarh','Goa','Gujarat','Haryana','Himachal Pradesh','Jharkhand','Karnataka','Kerala','Madhya Pradesh','Maharashtra','Manipur','Meghalaya','Mizoram','Nagaland','Odisha','Punjab','Rajasthan','Sikkim','Tamil Nadu','Telangana','Tripura','Uttar Pradesh','Uttarakhand','West Bengal','Andaman and Nicobar Islands','Chandigarh','Dadra and Nagar Haveli and Daman and Diu','Delhi','Jammu and Kashmir','Ladakh','Lakshadweep','Puducherry'];
    for (const language of supportedLocales.filter((code) => code !== 'en')) {
      for (const state of states) expect(localizeKnownLocation(state, language), `${language}:${state}`).not.toBe(state);
    }
    expect(states).toContain('Telangana');
    expect(localizeKnownLocation('Unknown village', 'te')).toBe('Unknown village');
  });

  it('includes source disclosure and response fallback keys in every supported language', () => {
    for (const language of supportedLocales.filter((code) => code !== 'en')) {
      expect(getLocalizationAudit(language).untranslatedKeys).not.toContain('sourceTextInEnglish');
      expect(getLocalizationAudit(language).untranslatedKeys).not.toContain('responseLanguageUnavailable');
    }
  });

  it('uses a selected-language fallback for mismatched assistant responses without rewriting the source', () => {
    const source = 'A response in the wrong language';
    for (const language of supportedLocales) {
      const fallback = assistantResponseForLanguage(source, 'en-IN', language);
      if (language === 'en') expect(fallback).toBe(source);
      else expect(fallback).toBe(translate(language, 'responseLanguageUnavailable'));
      expect(source).toBe('A response in the wrong language');
      expect(assistantResponseForLanguage(source, `${language}-IN`, language)).toBe(source);
    }
    expect(assistantResponseForLanguage(source, undefined, 'te')).toBe(source);
  });

  it('keeps the direct component dictionaries in sync with the supplemental translation path', () => {
    for (const language of supportedLocales) {
      for (const key of Object.keys(messages.en) as Array<keyof typeof messages.en>) {
        expect(messages[language][key], `${language}:${key}`).toBe(translate(language, key));
      }
    }
  });
});
