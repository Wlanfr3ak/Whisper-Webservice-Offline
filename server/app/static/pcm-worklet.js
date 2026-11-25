/* WhisperVM AudioWorklet: sammelt Float32-Frames und postet
   ~128-ms-Pakete (2048 Samples) an den Hauptthread. */
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.acc = [];
    this.len = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      this.acc.push(ch.slice(0));
      this.len += ch.length;
      if (this.len >= 2048) {
        const out = new Float32Array(this.len);
        let off = 0;
        for (const a of this.acc) { out.set(a, off); off += a.length; }
        this.port.postMessage(out, [out.buffer]);
        this.acc = [];
        this.len = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCapture);
