import { useRef, useCallback } from 'react'

// Single shared analyser hook — caller passes audio element
export function useAudioAnalyzer() {
  const ctxRef = useRef(null)
  const analyserRef = useRef(null)
  const srcRef = useRef(null)
  const dataRef = useRef(null)

  const attach = useCallback((audioEl) => {
    if (!audioEl) return null
    try {
      if (!ctxRef.current) ctxRef.current = new (window.AudioContext || window.webkitAudioContext)()
      const ctx = ctxRef.current
      if (ctx.state === 'suspended') ctx.resume()
      if (srcRef.current) { try{ srcRef.current.disconnect() }catch{} }
      const src = ctx.createMediaElementSource(audioEl)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.65
      src.connect(analyser)
      analyser.connect(ctx.destination)
      srcRef.current = src
      analyserRef.current = analyser
      dataRef.current = new Uint8Array(analyser.frequencyBinCount)
      return analyser
    } catch(e){ console.warn('analyser fail',e); return null }
  }, [])

  const getMetrics = useCallback(() => {
    const an = analyserRef.current
    const data = dataRef.current
    if (!an || !data) return { volume:0, viseme:0, bands:[0,0,0] }
    an.getByteFrequencyData(data)
    // bands
    const bass = avg(data, 1, 10)
    const mid  = avg(data, 10, 50)
    const hi   = avg(data, 50, 150)
    const total = (bass*0.5 + mid*0.8 + hi*0.4)/255
    const volume = Math.min(1, Math.pow(total/0.35, 0.9)) // expand low volumes
    // viseme classification via band ratios
    let viseme = 0
    const max = Math.max(bass, mid, hi)
    if (max < 8) viseme = 0 // closed silence
    else if (hi > mid*1.2 && hi > bass) viseme = 4 // f/v sibilant
    else if (bass > mid*1.3) viseme = 3 // o/u round (low)
    else if (mid > hi && mid > bass*0.9) viseme = 2 // a wide
    else viseme = 1 // e/i small
    return { volume, viseme, bands:[bass,mid,hi] }
  }, [])

  return { attach, getMetrics, ctxRef }
}

function avg(arr, from, to){
  let s=0, n=0
  for(let i=from;i<to && i<arr.length;i++){ s+=arr[i]; n++ }
  return n? s/n : 0
}
