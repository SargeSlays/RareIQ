/* Local operator audio gate. Audio stays in this graph; only state crosses the port. */
class StudioNoiseGate extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = false;
    this.thresholdDb = -45;
    this.threshold = 10 ** (this.thresholdDb / 20);
    this.energy = 0;
    this.gain = 1;
    this.open = false;
    this.hold = 0;
    this.frames = 0;
    this.lastStatusFrame = -Infinity;
    this.lastStatus = null;
    this.envelopeCoefficient = Math.exp(-1 / (sampleRate * 0.010));
    this.attackCoefficient = Math.exp(-1 / (sampleRate * 0.005));
    this.releaseCoefficient = Math.exp(-1 / (sampleRate * 0.100));
    this.holdFrames = Math.ceil(sampleRate * 0.150);
    this.statusInterval = Math.ceil(sampleRate * 0.100);
    this.port.onmessage = event => {
      const config = event.data;
      if (!config || config.type !== 'configure') return;
      if (typeof config.thresholdDb === 'number' && Number.isFinite(config.thresholdDb)) {
        this.thresholdDb = Math.max(-70, Math.min(-10, config.thresholdDb));
        this.threshold = 10 ** (this.thresholdDb / 20);
      }
      if (typeof config.enabled === 'boolean' && config.enabled !== this.enabled) {
        this.enabled = config.enabled;
        this.energy = 0;
        this.open = false;
        this.hold = 0;
        this.gain = this.enabled ? 0 : 1;
      }
    };
  }

  process(inputs, outputs) {
    const input = inputs[0] || [];
    const output = outputs[0] || [];
    const length = output[0]?.length || input[0]?.length || 128;
    if (!this.enabled) {
      for (let channel = 0; channel < output.length; channel++) {
        if (input[channel]) output[channel].set(input[channel]);
        else output[channel].fill(0);
      }
    } else {
      for (let index = 0; index < length; index++) {
        let power = 0;
        for (const channel of input) {
          const sample = Number.isFinite(channel[index]) ? channel[index] : 0;
          power += sample * sample;
        }
        power /= Math.max(1, input.length);
        this.energy = this.envelopeCoefficient * this.energy + (1 - this.envelopeCoefficient) * power;
        const rms = Math.sqrt(this.energy);
        if (!this.open && rms >= this.threshold) {
          this.open = true;
          this.hold = this.holdFrames;
        } else if (this.open) {
          if (rms >= this.threshold * (10 ** (-6 / 20))) this.hold = this.holdFrames;
          else if (this.hold > 0) this.hold--;
          else this.open = false;
        }
        const target = this.open ? 1 : 0;
        const coefficient = this.open ? this.attackCoefficient : this.releaseCoefficient;
        this.gain = target + coefficient * (this.gain - target);
        if (!this.open && this.gain < 1e-7) this.gain = 0;
        for (let channel = 0; channel < output.length; channel++) {
          const sample = input[channel]?.[index];
          output[channel][index] = Number.isFinite(sample) ? sample * this.gain : 0;
        }
      }
    }
    this.frames += length;
    const state = !this.enabled ? 'bypass' : this.open ? 'open' : 'closed';
    if (state !== this.lastStatus && this.frames - this.lastStatusFrame >= this.statusInterval) {
      this.port.postMessage({type: 'status', state});
      this.lastStatus = state;
      this.lastStatusFrame = this.frames;
    }
    return true;
  }
}

registerProcessor('studio-noise-gate', StudioNoiseGate);
