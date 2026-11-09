/** Browser capture helpers. Audio stays in memory until explicit upload. */
export async function makeWavBlob(source: Blob): Promise<Blob> {
  const Context = window.AudioContext ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Context) throw new Error('Audio recording is not supported in this browser.');
  const context = new Context();
  try {
    const decoded = await context.decodeAudioData(await source.arrayBuffer());
    if (decoded.duration > 30) throw new Error('Recordings must be 30 seconds or shorter.');
    const rate = 16000; const length = Math.ceil(decoded.duration * rate); const mono = new Float32Array(length);
    for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
      const input = decoded.getChannelData(channel);
      for (let i = 0; i < length; i += 1) mono[i] += (input[Math.min(input.length - 1, Math.floor(i * decoded.sampleRate / rate))] ?? 0) / decoded.numberOfChannels;
    }
    const buffer = new ArrayBuffer(44 + length * 2); const view = new DataView(buffer);
    const write = (offset: number, value: string) => [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
    write(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); write(8, 'WAVE'); write(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data'); view.setUint32(40, length * 2, true);
    for (let i = 0; i < length; i += 1) { const sample = Math.max(-1, Math.min(1, mono[i])); view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true); }
    return new Blob([buffer], { type: 'audio/wav' });
  } finally { await context.close(); }
}
