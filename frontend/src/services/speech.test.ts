import { describe, expect, it } from 'vitest';
import { prismaInputEnabled, supportedSpeechLocales, timbreOutputEnabled } from './speech';

describe('backend-controlled Gnani voice capabilities', () => {
  it('keeps the seven supported language codes available to the voice UI', () => {
    expect(supportedSpeechLocales).toEqual(['te', 'en', 'hi', 'ta', 'kn', 'ml', 'mr']);
  });

  it('requires the global backend switch and modality switch before showing a voice feature', () => {
    expect(prismaInputEnabled({ gnani_live_api_enabled: true, prisma_input_enabled: true, timbre_output_enabled: false })).toBe(true);
    expect(prismaInputEnabled({ gnani_live_api_enabled: false, prisma_input_enabled: true, timbre_output_enabled: false })).toBe(false);
    expect(timbreOutputEnabled({ gnani_live_api_enabled: true, prisma_input_enabled: false, timbre_output_enabled: true })).toBe(true);
    expect(timbreOutputEnabled({ gnani_live_api_enabled: true, prisma_input_enabled: false, timbre_output_enabled: false })).toBe(false);
    expect(prismaInputEnabled(null)).toBe(false);
    expect(timbreOutputEnabled(undefined)).toBe(false);
  });
});
