/* Local JPEG inference only. No capture, remote API, identity or production action. */
'use strict';
importScripts('/static/production_vision_model.js');
let detector = null, mode = null;
self.onmessage = async function ({data}) {
  try {
    if (data.type === 'init') {
      const {FilesetResolver, GestureRecognizer, FaceLandmarker} = await import('/api/production/vision/assets/vision_bundle.mjs');
      const files = await FilesetResolver.forVisionTasks('/api/production/vision/assets/wasm');
      mode = data.mode;
      if (detector) detector.close();
      detector = mode === 'hands'
        ? await GestureRecognizer.createFromOptions(files, {
          baseOptions: {modelAssetPath: '/api/production/vision/assets/gesture_recognizer.task', delegate: 'CPU'},
          runningMode: 'IMAGE', numHands: 2, minHandDetectionConfidence: .8, minHandPresenceConfidence: .8})
        : await FaceLandmarker.createFromOptions(files, {
          baseOptions: {modelAssetPath: '/api/production/vision/assets/face_landmarker.task', delegate: 'CPU'},
          runningMode: 'IMAGE', numFaces: 2, minFaceDetectionConfidence: .8, minFacePresenceConfidence: .8,
          outputFacialTransformationMatrixes: true});
      self.postMessage({id: data.id, ok: true});
    } else if (data.type === 'infer' && detector) {
      try {
        const output = mode === 'hands' ? detector.recognize(data.image) : detector.detect(data.image);
        self.postMessage({id: data.id, ok: true, observation: self.ProducerVisionModel.observation(output, mode)});
      } finally { data.image.close(); }
    } else throw new Error('not_initialized');
  } catch (_) {
    self.postMessage({id: data.id, ok: false, reason: 'vision_model_unavailable'});
  }
};
