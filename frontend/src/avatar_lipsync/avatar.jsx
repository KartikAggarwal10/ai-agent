import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { Play, Square } from 'lucide-react';

const COLORS = {
  bg: '#1B1730',
  panel: '#241F3D',
  panelBorder: '#382E5C',
  amber: '#F2A65A',
  teal: '#6FD6C1',
  text: '#F5F2ED',
  muted: '#ABA3C8',
};

const VISEME_TARGETS = {
  closed: { x: 0.9, y: 0.06 },
  small: { x: 0.55, y: 0.26 },
  wide: { x: 1.0, y: 0.55 },
  round: { x: 0.45, y: 0.5 },
};

function pickViseme(word) {
  const w = (word || '').toLowerCase().replace(/[^a-z]/g, '');
  if (!w) return 'small';
  if (/(oo|ou|ow|oa|[ou])/.test(w)) return 'round';
  if (/[a]/.test(w)) return 'wide';
  if (/^[bpm]/.test(w)) return 'closed';
  return 'small';
}

export default function TalkingAvatar() {
  const mountRef = useRef(null);
  const threeRef = useRef({});
  const speakingRef = useRef(false);
  const visemeRef = useRef('closed');
  const mouthScaleRef = useRef({ x: 0.9, y: 0.06 });
  const pointerRef = useRef({ x: 0, y: 0 });

  const [supported, setSupported] = useState(true);
  const [voices, setVoices] = useState([]);
  const [voiceURI, setVoiceURI] = useState('');
  const [text, setText] = useState(
    "Hello! I'm doing my best to move my mouth in time with these words."
  );
  const [rate, setRate] = useState(1);
  const [pitch, setPitch] = useState(1);
  const [speaking, setSpeaking] = useState(false);

  // ---- Three.js scene setup ----
  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    const width = container.clientWidth || 400;
    const height = container.clientHeight || 400;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 100);
    camera.position.set(0, 0.05, 4.4);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0x554466, 0.9));
    const key = new THREE.PointLight(0xf2a65a, 1.2, 20);
    key.position.set(2.5, 2.5, 3);
    scene.add(key);
    const fillLight = new THREE.PointLight(0x6fd6c1, 0.6, 20);
    fillLight.position.set(-3, -1, 2);
    scene.add(fillLight);

    const head = new THREE.Group();
    scene.add(head);

    const headMesh = new THREE.Mesh(
      new THREE.SphereGeometry(1.15, 48, 48),
      new THREE.MeshStandardMaterial({ color: 0xe7c9a9, roughness: 0.6, metalness: 0.05 })
    );
    head.add(headMesh);

    function makeEye(x) {
      const g = new THREE.Group();
      const white = new THREE.Mesh(
        new THREE.SphereGeometry(0.17, 24, 24),
        new THREE.MeshStandardMaterial({ color: 0xfffdf6, roughness: 0.3 })
      );
      g.add(white);
      const pupil = new THREE.Mesh(
        new THREE.SphereGeometry(0.085, 16, 16),
        new THREE.MeshStandardMaterial({ color: 0x2b1e3d, roughness: 0.4 })
      );
      pupil.position.z = 0.13;
      g.add(pupil);
      g.position.set(x, 0.32, 0.96);
      return g;
    }
    const eyeL = makeEye(-0.42);
    const eyeR = makeEye(0.42);
    head.add(eyeL, eyeR);

    function makeBrow(x) {
      const brow = new THREE.Mesh(
        new THREE.BoxGeometry(0.34, 0.06, 0.06),
        new THREE.MeshStandardMaterial({ color: 0x5b4636, roughness: 0.7 })
      );
      brow.position.set(x, 0.58, 1.0);
      brow.rotation.z = x < 0 ? 0.12 : -0.12;
      return brow;
    }
    head.add(makeBrow(-0.42), makeBrow(0.42));

    const mouth = new THREE.Mesh(
      new THREE.SphereGeometry(0.34, 24, 24),
      new THREE.MeshStandardMaterial({ color: 0x2b1e3d, roughness: 0.5 })
    );
    mouth.position.set(0, -0.42, 0.98);
    mouth.scale.set(0.9, 0.06, 0.35);
    head.add(mouth);

    threeRef.current = {
      scene,
      camera,
      renderer,
      head,
      mouth,
      eyeL,
      eyeR,
      raf: null,
      clock: new THREE.Clock(),
      blinkTimer: 0,
      nextBlink: 2 + Math.random() * 3,
    };

    function handleResize() {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    function handlePointerMove(e) {
      const rect = container.getBoundingClientRect();
      pointerRef.current = {
        x: ((e.clientX - rect.left) / rect.width) * 2 - 1,
        y: ((e.clientY - rect.top) / rect.height) * 2 - 1,
      };
    }
    container.addEventListener('pointermove', handlePointerMove);

    function animate() {
      const t = threeRef.current;
      const elapsed = t.clock.getElapsedTime();
      const delta = t.clock.getDelta();

      head.position.y = Math.sin(elapsed * 1.1) * 0.03;

      const targetRotY = pointerRef.current.x * 0.35;
      const targetRotX = -pointerRef.current.y * 0.2;
      head.rotation.y += (targetRotY - head.rotation.y) * 0.06;
      head.rotation.x += (targetRotX - head.rotation.x) * 0.06;

      t.blinkTimer += delta;
      let blinkScale = 1;
      if (t.blinkTimer > t.nextBlink) {
        const phase = t.blinkTimer - t.nextBlink;
        if (phase < 0.12) {
          blinkScale = 1 - phase / 0.12;
        } else if (phase < 0.22) {
          blinkScale = (phase - 0.12) / 0.1;
        } else {
          t.blinkTimer = 0;
          t.nextBlink = 2 + Math.random() * 3.5;
        }
      }
      eyeL.scale.y = Math.max(0.08, blinkScale);
      eyeR.scale.y = Math.max(0.08, blinkScale);

      const target = VISEME_TARGETS[visemeRef.current] || VISEME_TARGETS.closed;
      let tx = target.x;
      let ty = target.y;
      if (speakingRef.current) {
        const chatter = Math.sin(elapsed * 16) * 0.12 + Math.sin(elapsed * 27) * 0.06;
        ty = Math.max(0.04, ty + chatter);
      }
      const cur = mouthScaleRef.current;
      cur.x += (tx - cur.x) * 0.25;
      cur.y += (ty - cur.y) * 0.35;
      mouth.scale.set(cur.x, cur.y, 0.35);

      renderer.render(scene, camera);
      t.raf = requestAnimationFrame(animate);
    }
    animate();

    return () => {
      cancelAnimationFrame(threeRef.current.raf);
      resizeObserver.disconnect();
      container.removeEventListener('pointermove', handlePointerMove);
      scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) obj.material.dispose();
      });
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  // ---- Voice loading ----
  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      setSupported(false);
      return;
    }
    function loadVoices() {
      const v = window.speechSynthesis.getVoices();
      if (v && v.length) {
        setVoices(v);
        setVoiceURI((prev) => prev || v[0].voiceURI);
      }
    }
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
    return () => {
      if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = null;
    };
  }, []);

  const handleSpeak = useCallback(() => {
    if (!supported || !text.trim()) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    const chosen = voices.find((v) => v.voiceURI === voiceURI);
    if (chosen) utter.voice = chosen;
    utter.rate = rate;
    utter.pitch = pitch;

    utter.onstart = () => {
      speakingRef.current = true;
      setSpeaking(true);
    };
    utter.onboundary = (event) => {
      if (event.name && event.name !== 'word') return;
      const word = text.slice(event.charIndex, event.charIndex + (event.charLength || 8));
      visemeRef.current = pickViseme(word);
    };
    utter.onend = () => {
      speakingRef.current = false;
      visemeRef.current = 'closed';
      setSpeaking(false);
    };
    utter.onerror = () => {
      speakingRef.current = false;
      visemeRef.current = 'closed';
      setSpeaking(false);
    };
    window.speechSynthesis.speak(utter);
  }, [supported, text, voices, voiceURI, rate, pitch]);

  const handleStop = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    speakingRef.current = false;
    visemeRef.current = 'closed';
    setSpeaking(false);
  }, [supported]);

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center p-4 md:p-8"
      style={{ background: COLORS.bg, fontFamily: "'Inter', sans-serif", color: COLORS.text }}
    >
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap');`}</style>

      <div className="w-full max-w-5xl">
        <div className="mb-6 md:mb-8">
          <h1
            className="text-3xl md:text-4xl font-bold tracking-tight"
            style={{ fontFamily: "'Space Grotesk', sans-serif" }}
          >
            Lip Sync Lab
          </h1>
          <p className="mt-2 text-sm md:text-base" style={{ color: COLORS.muted }}>
            Type something, choose a voice, and watch the puppet talk along.
          </p>
        </div>

        <div className="flex flex-col md:flex-row gap-6">
          <div className="w-full md:w-1/2">
            <div
              ref={mountRef}
              className="w-full aspect-square rounded-3xl overflow-hidden"
              style={{
                background: `radial-gradient(circle at 50% 35%, ${COLORS.panel}, ${COLORS.bg} 75%)`,
                border: `1px solid ${COLORS.panelBorder}`,
              }}
            />
            <div className="mt-3 h-5 flex items-center gap-2 text-sm" style={{ color: COLORS.teal }}>
              {speaking && (
                <>
                  <span className="flex gap-0.5 items-end h-4">
                    {[0, 1, 2, 3].map((i) => (
                      <span
                        key={i}
                        className="w-1 rounded-full animate-pulse"
                        style={{ background: COLORS.teal, height: `${6 + (i % 3) * 4}px` }}
                      />
                    ))}
                  </span>
                  Speaking…
                </>
              )}
            </div>
          </div>

          <div
            className="w-full md:w-1/2 rounded-3xl p-5 md:p-6"
            style={{ background: COLORS.panel, border: `1px solid ${COLORS.panelBorder}` }}
          >
            {!supported ? (
              <div className="text-sm" style={{ color: COLORS.muted }}>
                This browser doesn't support built-in text-to-speech. Try Chrome or Edge on desktop.
              </div>
            ) : (
              <>
                <label className="block text-sm font-medium mb-2">Give it something to say</label>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={4}
                  className="w-full rounded-xl p-3 text-sm resize-none outline-none"
                  style={{ background: COLORS.bg, color: COLORS.text, border: `1px solid ${COLORS.panelBorder}` }}
                  placeholder="Type what you want the puppet to say..."
                />

                <div className="mt-4">
                  <label className="block text-sm font-medium mb-2">Voice</label>
                  <select
                    value={voiceURI}
                    onChange={(e) => setVoiceURI(e.target.value)}
                    className="w-full rounded-xl p-2.5 text-sm outline-none"
                    style={{ background: COLORS.bg, color: COLORS.text, border: `1px solid ${COLORS.panelBorder}` }}
                  >
                    {voices.map((v) => (
                      <option key={v.voiceURI} value={v.voiceURI}>
                        {v.name} ({v.lang})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2">Speed: {rate.toFixed(1)}x</label>
                    <input
                      type="range"
                      min="0.5"
                      max="1.8"
                      step="0.1"
                      value={rate}
                      onChange={(e) => setRate(parseFloat(e.target.value))}
                      className="w-full"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2">Pitch: {pitch.toFixed(1)}</label>
                    <input
                      type="range"
                      min="0.5"
                      max="1.8"
                      step="0.1"
                      value={pitch}
                      onChange={(e) => setPitch(parseFloat(e.target.value))}
                      className="w-full"
                    />
                  </div>
                </div>

                <div className="mt-5 flex gap-3">
                  <button
                    onClick={handleSpeak}
                    disabled={speaking}
                    className="flex-1 flex items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold disabled:opacity-40"
                    style={{ background: COLORS.amber, color: '#241705' }}
                  >
                    <Play size={16} /> Speak
                  </button>
                  <button
                    onClick={handleStop}
                    disabled={!speaking}
                    className="flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold disabled:opacity-40"
                    style={{ background: 'transparent', color: COLORS.text, border: `1px solid ${COLORS.panelBorder}` }}
                  >
                    <Square size={16} /> Stop
                  </button>
                </div>

                <p className="mt-5 text-xs leading-relaxed" style={{ color: COLORS.muted }}>
                  The mouth shape is guessed from each word as your browser speaks it, not from real
                  phoneme timing — a simplified stand-in for the viseme systems production tools use.
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}