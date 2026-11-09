/** Client-side capability helpers for the backend-controlled Prisma input path. */
export const supportedSpeechLocales = ['te', 'en', 'hi', 'ta', 'kn', 'ml', 'mr'] as const;

export type VoiceProviderCapabilities = {
  gnani_live_api_enabled?: boolean;
  prisma_input_enabled?: boolean;
  timbre_output_enabled?: boolean;
};

export function prismaInputEnabled(capabilities: VoiceProviderCapabilities | null | undefined): boolean {
  return capabilities?.gnani_live_api_enabled === true && capabilities.prisma_input_enabled === true;
}

export function timbreOutputEnabled(capabilities: VoiceProviderCapabilities | null | undefined): boolean {
  return capabilities?.gnani_live_api_enabled === true && capabilities.timbre_output_enabled === true;
}
