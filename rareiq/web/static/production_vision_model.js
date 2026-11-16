(function (root) {
  'use strict';
  const gestures = {Open_Palm: 'open_palm', Thumb_Up: 'thumbs_up', Victory: 'victory'};
  function pose(matrix) {
    if (!matrix || matrix.length !== 16 || !Array.from(matrix).every(Number.isFinite)) return null;
    // MediaPipe's column-major transform: forward axis, not pupil/eye gaze.
    const x = matrix[8], y = matrix[9], z = matrix[10];
    const norm = Math.hypot(x, y, z);
    if (norm < .5 || norm > 1.5) return null;
    return {yaw: Math.atan2(x, z) * 180 / Math.PI,
      pitch: Math.atan2(-y, Math.hypot(x, z)) * 180 / Math.PI};
  }
  function observation(result, mode) {
    const base = {hand_count: 0, gesture: 'neutral', gesture_score: 1, face_count: 0, yaw: null, pitch: null};
    if (mode === 'hands') {
      base.hand_count = Math.min(2, (result.landmarks || []).length);
      const first = result.gestures && result.gestures[0] && result.gestures[0][0];
      if (base.hand_count === 1 && first) {
        base.gesture = gestures[first.categoryName] || 'neutral';
        base.gesture_score = Number.isFinite(first.score) ? first.score : 0;
      } else if (base.hand_count === 1) base.gesture_score = 0;
    } else {
      base.face_count = Math.min(2, (result.faceLandmarks || []).length);
      const transform = result.facialTransformationMatrixes && result.facialTransformationMatrixes[0];
      const direction = transform && pose(transform.data);
      if (base.face_count === 1 && direction) Object.assign(base, direction);
    }
    return base;
  }
  const api = {pose, observation};
  if (typeof module !== 'undefined') module.exports = api;
  if (root) root.ProducerVisionModel = api;
})(typeof self !== 'undefined' ? self : globalThis);
