import { useEffect, useRef } from 'react'

/*
  Beautiful anime-style girl avatar drawn with Canvas.
  Lip-sync: reads volume + viseme from analyzer, drives:
    - mouth shape (closed / small / wide / o / f)
    - jaw drop
    - lip stretch
    - optional teeth/tongue
  Plus: blinks every 2.5-5s, micro head bob on volume, breathing, eye sparkle.
  No image needed — pure vector, looks crisp at any size.
*/

export default function AvatarCanvas({ analyserHook, audioRef, speaking, status }) {
  const canvasRef = useRef(null)
  const rafRef = useRef(0)

  // animated state
  const mouthRef = useRef({ viseme:0, open:0, jaw:0, targetOpen:0, targetViseme:0 })
  const blinkRef = useRef({ t:0, next: 2200, closing: false, phase:0 })
  const timeRef = useRef(0)

  useEffect(()=>{
    const canvas = canvasRef.current
    if(!canvas) return
    const ctx = canvas.getContext('2d')
    let w, h, dpr

    function resize(){
      dpr = Math.min(2, window.devicePixelRatio || 1)
      w = canvas.clientWidth * dpr
      h = canvas.clientHeight * dpr
      canvas.width = w; canvas.height = h
    }
    resize()
    window.addEventListener('resize', resize)

    function frame(now){
      rafRef.current = requestAnimationFrame(frame)
      timeRef.current = now
      // ---- analyser ----
      let volume=0, viseme=0
      if (speaking && analyserHook) {
        const m = analyserHook.getMetrics()
        volume = m.volume
        viseme = m.viseme
        // boost tiny volumes so mouth still moves
        if (volume > 0.06) {
          mouthRef.current.targetViseme = viseme
          mouthRef.current.targetOpen = Math.min(1, volume*1.35)
        } else {
          mouthRef.current.targetOpen *= 0.82
        }
      } else {
        mouthRef.current.targetOpen *= 0.88
        if (mouthRef.current.targetOpen < 0.02) mouthRef.current.targetOpen = 0
      }
      // smooth lerp
      const mr = mouthRef.current
      mr.open += (mr.targetOpen - mr.open) * 0.42
      mr.viseme += (mr.targetViseme - mr.viseme) * 0.35
      mr.jaw = mr.open * 0.9

      // blink logic
      const br = blinkRef.current
      br.t += 16
      if (!br.closing && br.t > br.next) { br.closing = true; br.phase = 0 }
      if (br.closing) {
        br.phase += 0.28
        if (br.phase >= 1) { br.closing=false; br.t=0; br.next= 2000 + Math.random()*3000 }
      }
      const blink = br.closing ? Math.sin(br.phase*Math.PI) : 0 // 0..1..0

      draw(ctx, w, h, dpr, mr.open, mr.viseme, mr.jaw, blink, volume, now, status, speaking)
    }
    rafRef.current = requestAnimationFrame(frame)
    return ()=>{ cancelAnimationFrame(rafRef.current); window.removeEventListener('resize', resize) }
  }, [speaking, status, analyserHook])

  return (
    <div className="avatar-wrap">
      <canvas ref={canvasRef} className="avatar-canvas" style={{width:'100%', height:'100%'}} />
      {/* subtle speaking badge */}
      <div className={`speak-badge ${speaking ? 'on':''}`}>
        <span className="dot" /> {speaking ? 'Speaking…' : status==='thinking' ? 'Thinking…' : status==='listening' ? 'Listening…' : 'Ready'}
      </div>
    </div>
  )
}

function draw(ctx, w, h, dpr, open, viseme, jaw, blink, volume, now, status, speaking){
  ctx.clearRect(0,0,w,h)
  const cx = w*0.5
  const cy = h*0.52
  const S = Math.min(w,h) * 0.88 // scale

  // background soft glow
  const g = ctx.createRadialGradient(cx, cy+S*0.15, S*0.1, cx, cy+S*0.15, S*0.85)
  g.addColorStop(0, '#ffd6e8')
  g.addColorStop(0.5, '#ffeef6')
  g.addColorStop(1, '#fff0f7')
  ctx.fillStyle = g
  ctx.fillRect(0,0,w,h)

  // breathing + head bob
  const breath = Math.sin(now*0.0011)* S*0.006
  const bob = speaking ? volume* S*0.02 : 0
  const hx = cx
  const hy = cy + breath - bob*0.3

  ctx.save()
  ctx.translate(hx, hy)

  // subtle head sway
  const sway = speaking ? Math.sin(now*0.005)* volume*6 : Math.sin(now*0.0007)*2
  ctx.translate(sway, 0)

  // ---- shadow ----
  ctx.fillStyle = 'rgba(180,90,130,0.12)'
  ctx.beginPath()
  ctx.ellipse(0, S*0.48, S*0.22, S*0.07, 0, 0, Math.PI*2)
  ctx.fill()

  // ---- neck ----
  ctx.fillStyle = '#ffdfd1'
  ctx.beginPath()
  ctx.roundRect(-S*0.07, S*0.18, S*0.14, S*0.14, S*0.04)
  ctx.fill()

  // ---- hair back ----
  ctx.fillStyle = '#3b1f2a' // dark chestnut
  hairBack(ctx, S)

  // ---- face shape ----
  ctx.fillStyle = '#ffddd0' // skin
  facePath(ctx, S)
  ctx.fill()
  // cheek blush
  ctx.fillStyle = 'rgba(255,120,160,0.22)'
  ctx.beginPath(); ctx.ellipse(-S*0.13, S*0.06, S*0.07, S*0.045, 0,0,Math.PI*2); ctx.fill()
  ctx.beginPath(); ctx.ellipse( S*0.13, S*0.06, S*0.07, S*0.045, 0,0,Math.PI*2); ctx.fill()

  // ---- ears ----
  ctx.fillStyle = '#ffcfbf'
  ctx.beginPath(); ctx.ellipse(-S*0.195, -S*0.02, S*0.03, S*0.05, -0.2,0,Math.PI*2); ctx.fill()
  ctx.beginPath(); ctx.ellipse( S*0.195, -S*0.02, S*0.03, S*0.05,  0.2,0,Math.PI*2); ctx.fill()

  // ---- hair front bangs ----
  ctx.fillStyle = '#3b1f2a'
  hairFront(ctx, S)

  // ---- eyes ----
  const eyeY = -S*0.06
  const eyeO = blink // 0 open, 1 closed
  drawEye(ctx, -S*0.09, eyeY, S, eyeO, -1)
  drawEye(ctx,  S*0.09, eyeY, S, eyeO,  1)

  // ---- nose ----
  ctx.strokeStyle = 'rgba(180,110,110,0.35)'
  ctx.lineWidth = S*0.004
  ctx.beginPath()
  ctx.moveTo(0, -S*0.005); ctx.lineTo(S*0.008, S*0.02); ctx.stroke()
  ctx.fillStyle = 'rgba(180,110,110,0.18)'
  ctx.beginPath(); ctx.ellipse(S*0.006, S*0.022, S*0.012, S*0.006,0,0,Math.PI*2); ctx.fill()

  // ---- mouth ----
  const mouthY = S*0.11 + jaw*S*0.06
  drawMouth(ctx, 0, mouthY, S, open, viseme)

  // ---- hair shine ----
  ctx.fillStyle = 'rgba(255,255,255,0.28)'
  ctx.beginPath()
  ctx.ellipse(-S*0.12, -S*0.19, S*0.08, S*0.018, -0.6,0,Math.PI*2); ctx.fill()

  // ---- collar ----
  ctx.fillStyle = '#ffffff'
  ctx.beginPath()
  ctx.moveTo(-S*0.18, S*0.30); ctx.lineTo(0, S*0.36); ctx.lineTo(S*0.18, S*0.30)
  ctx.lineTo(S*0.12, S*0.27); ctx.lineTo(-S*0.12, S*0.27); ctx.closePath(); ctx.fill()
  ctx.fillStyle = '#ff6b9d'
  ctx.beginPath(); ctx.moveTo(-S*0.02, S*0.30); ctx.lineTo(0, S*0.34); ctx.lineTo(S*0.02, S*0.30); ctx.lineTo(0, S*0.32); ctx.closePath(); ctx.fill()

  // ---- speaking ring ----
  if (speaking && volume>0.08){
    ctx.strokeStyle = `rgba(255,105,160,${0.18+volume*0.35})`
    ctx.lineWidth = S*0.008
    ctx.beginPath(); ctx.ellipse(0, S*0.04, S*0.30+volume*S*0.08, S*0.38+volume*S*0.06, 0,0,Math.PI*2); ctx.stroke()
  }

  ctx.restore()
}

function facePath(ctx,S){
  ctx.beginPath()
  ctx.moveTo(-S*0.19, -S*0.08)
  ctx.bezierCurveTo(-S*0.20, -S*0.18, -S*0.14, -S*0.24, 0, -S*0.245)
  ctx.bezierCurveTo( S*0.14, -S*0.24,  S*0.20, -S*0.18,  S*0.19, -S*0.08)
  ctx.bezierCurveTo( S*0.20,  S*0.06,  S*0.12,  S*0.17, 0, S*0.19)
  ctx.bezierCurveTo(-S*0.12,  S*0.17, -S*0.20,  S*0.06, -S*0.19, -S*0.08)
  ctx.closePath()
}
function hairBack(ctx,S){
  ctx.beginPath()
  ctx.moveTo(-S*0.24, -S*0.18)
  ctx.bezierCurveTo(-S*0.32, -S*0.06, -S*0.30, S*0.22, -S*0.18, S*0.34)
  ctx.lineTo(-S*0.10, S*0.34)
  ctx.bezierCurveTo(-S*0.16, S*0.10, -S*0.18, -S*0.10, -S*0.14, -S*0.20)
  ctx.closePath(); ctx.fill()
  ctx.beginPath()
  ctx.moveTo(S*0.24, -S*0.18)
  ctx.bezierCurveTo(S*0.32, -S*0.06, S*0.30, S*0.22, S*0.18, S*0.34)
  ctx.lineTo(S*0.10, S*0.34)
  ctx.bezierCurveTo(S*0.16, S*0.10, S*0.18, -S*0.10, S*0.14, -S*0.20)
  ctx.closePath(); ctx.fill()
  // length
  ctx.beginPath()
  ctx.moveTo(-S*0.22, S*0.08); ctx.lineTo(-S*0.24, S*0.32); ctx.lineTo(-S*0.18, S*0.34); ctx.lineTo(-S*0.14, S*0.10); ctx.closePath(); ctx.fill()
  ctx.beginPath()
  ctx.moveTo(S*0.22, S*0.08); ctx.lineTo(S*0.24, S*0.32); ctx.lineTo(S*0.18, S*0.34); ctx.lineTo(S*0.14, S*0.10); ctx.closePath(); ctx.fill()
}
function hairFront(ctx,S){
  ctx.beginPath()
  ctx.moveTo(-S*0.20, -S*0.16)
  ctx.bezierCurveTo(-S*0.18, -S*0.26, -S*0.06, -S*0.28, 0, -S*0.27)
  ctx.bezierCurveTo(S*0.06, -S*0.28, S*0.18, -S*0.26, S*0.20, -S*0.16)
  ctx.bezierCurveTo(S*0.16, -S*0.10, S*0.08, -S*0.12, S*0.04, -S*0.08)
  ctx.bezierCurveTo(S*0.02, -S*0.04, -S*0.02, -S*0.04, -S*0.04, -S*0.08)
  ctx.bezierCurveTo(-S*0.08, -S*0.12, -S*0.16, -S*0.10, -S*0.20, -S*0.16)
  ctx.closePath(); ctx.fill()
  // side strands
  ctx.beginPath()
  ctx.moveTo(-S*0.20, -S*0.12); ctx.lineTo(-S*0.23, S*0.12); ctx.lineTo(-S*0.19, S*0.10); ctx.lineTo(-S*0.16, -S*0.08); ctx.closePath(); ctx.fill()
  ctx.beginPath()
  ctx.moveTo(S*0.20, -S*0.12); ctx.lineTo(S*0.23, S*0.12); ctx.lineTo(S*0.19, S*0.10); ctx.lineTo(S*0.16, -S*0.08); ctx.closePath(); ctx.fill()
}

function drawEye(ctx, x, y, S, blink, side){
  ctx.save()
  ctx.translate(x,y)
  // white
  ctx.fillStyle = '#ffffff'
  const openH = S*0.085 * (1 - blink*0.92)
  const w = S*0.11, h = openH
  ctx.beginPath()
  // eye shape — almond
  ctx.moveTo(-w*0.5, 0)
  ctx.bezierCurveTo(-w*0.35, -h, w*0.35, -h, w*0.5, 0)
  ctx.bezierCurveTo(w*0.35, h, -w*0.35, h, -w*0.5, 0)
  ctx.closePath(); ctx.fill()
  if (blink > 0.85) { ctx.restore(); return }
  // iris
  ctx.fillStyle = '#6b3a2a' // warm brown
  ctx.beginPath(); ctx.arc(side*S*0.01, S*0.006, S*0.038, 0, Math.PI*2); ctx.fill()
  // darker ring
  ctx.strokeStyle = 'rgba(0,0,0,0.25)'; ctx.lineWidth = S*0.004
  ctx.beginPath(); ctx.arc(side*S*0.01, S*0.006, S*0.038, 0, Math.PI*2); ctx.stroke()
  // pupil
  ctx.fillStyle = '#1a0f0a'
  ctx.beginPath(); ctx.arc(side*S*0.01, S*0.006, S*0.022, 0, Math.PI*2); ctx.fill()
  // highlight
  ctx.fillStyle = 'rgba(255,255,255,0.95)'
  ctx.beginPath(); ctx.arc(-S*0.012+side*S*0.01, -S*0.008, S*0.010, 0, Math.PI*2); ctx.fill()
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.beginPath(); ctx.arc(S*0.010+side*S*0.01, S*0.012, S*0.005, 0, Math.PI*2); ctx.fill()
  // eyelid / lash
  ctx.strokeStyle = '#3b1f2a'; ctx.lineWidth = S*0.007
  ctx.beginPath()
  ctx.moveTo(-w*0.52, 0); ctx.bezierCurveTo(-w*0.3, -h*1.05, w*0.3, -h*1.05, w*0.52, 0); ctx.stroke()
  // lower lash
  ctx.strokeStyle = 'rgba(59,31,42,0.55)'; ctx.lineWidth = S*0.003
  ctx.beginPath()
  ctx.moveTo(-w*0.48, 0); ctx.bezierCurveTo(-w*0.2, h*1.05, w*0.2, h*1.05, w*0.48, 0); ctx.stroke()
  // blink lid overlay
  if (blink>0.05){
    ctx.fillStyle = '#ffcfbf'
    ctx.beginPath()
    ctx.moveTo(-w*0.52, 0)
    ctx.bezierCurveTo(-w*0.3, -h*1.1, w*0.3, -h*1.1, w*0.52, 0)
    ctx.lineTo(w*0.52, -h*blink*1.2)
    ctx.lineTo(-w*0.52, -h*blink*1.2)
    ctx.closePath(); ctx.fill()
  }
  ctx.restore()
}

function drawMouth(ctx, x, y, S, open, vis){
  // viseme: 0 closed, 1 i/e small, 2 a wide, 3 o round, 4 f teeth
  const v = Math.round(vis)
  // map viseme to mouth geometry
  let mw, mh, showTeeth=false, oRatio=1
  if (open < 0.04) { mw = S*0.055; mh = S*0.008 } // rest — soft smile
  else if (v===0)   { mw = S*0.05; mh = S*0.010 + open*S*0.04 }
  else if (v===1)   { mw = S*0.09; mh = S*0.020 + open*S*0.05; showTeeth=true }
  else if (v===2)   { mw = S*0.075; mh = S*0.035 + open*S*0.09; showTeeth=true }
  else if (v===3)   { mw = S*0.050; mh = S*0.040 + open*S*0.08; oRatio=0.85 }
  else              { mw = S*0.070; mh = S*0.020 + open*S*0.05; showTeeth=true } // f
  // clamp
  mw = Math.max(S*0.04, Math.min(S*0.11, mw))
  mh = Math.max(S*0.007, Math.min(S*0.11, mh))

  ctx.save()
  ctx.translate(x,y)

  if (open < 0.04) {
    // gentle smile line
    ctx.strokeStyle = '#b55a6e'
    ctx.lineWidth = S*0.006
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(-mw*0.5, 0); ctx.quadraticCurveTo(0, S*0.012, mw*0.5, 0)
    ctx.stroke()
    // tiny highlight
    ctx.fillStyle = 'rgba(255,120,150,0.18)'
    ctx.beginPath(); ctx.ellipse(0, S*0.008, mw*0.3, S*0.007, 0,0,Math.PI*2); ctx.fill()
    ctx.restore(); return
  }

  // outer lips
  ctx.fillStyle = '#c94a6a'
  ctx.beginPath()
  if (v===3) {
    // O shape — rounded
    ctx.ellipse(0, 0, mw*0.5*oRatio, mh*0.5, 0, 0, Math.PI*2)
  } else {
    ctx.moveTo(-mw*0.5, 0)
    ctx.bezierCurveTo(-mw*0.3, -mh*0.55, mw*0.3, -mh*0.55, mw*0.5, 0)
    ctx.bezierCurveTo(mw*0.3, mh*0.55, -mw*0.3, mh*0.55, -mw*0.5, 0)
    ctx.closePath()
  }
  ctx.fill()

  // inner mouth dark
  ctx.fillStyle = '#3b0a14'
  ctx.beginPath()
  if (v===3) ctx.ellipse(0, S*0.003, mw*0.32, mh*0.32, 0,0,Math.PI*2)
  else {
    ctx.moveTo(-mw*0.38, S*0.001)
    ctx.bezierCurveTo(-mw*0.22, -mh*0.30, mw*0.22, -mh*0.30, mw*0.38, S*0.001)
    ctx.bezierCurveTo(mw*0.22, mh*0.30, -mw*0.22, mh*0.30, -mw*0.38, S*0.001)
    ctx.closePath()
  }
  ctx.fill()

  // teeth
  if (showTeeth && mh > S*0.022) {
    ctx.fillStyle = '#fff8f0'
    const th = Math.min(mh*0.42, S*0.022)
    ctx.beginPath()
    if (v===3) ctx.ellipse(0, -mh*0.08, mw*0.22, th*0.5, 0,0,Math.PI*2)
    else {
      ctx.moveTo(-mw*0.28, -mh*0.12)
      ctx.bezierCurveTo(-mw*0.15, -mh*0.22, mw*0.15, -mh*0.22, mw*0.28, -mh*0.12)
      ctx.lineTo(mw*0.28, -mh*0.12+th)
      ctx.lineTo(-mw*0.28, -mh*0.12+th)
      ctx.closePath()
    }
    ctx.fill()
    // teeth line
    ctx.strokeStyle = 'rgba(0,0,0,0.08)'; ctx.lineWidth = S*0.002
    ctx.beginPath(); ctx.moveTo(0, -mh*0.12); ctx.lineTo(0, -mh*0.12+th); ctx.stroke()
  }

  // tongue for wide open
  if (v===2 && mh > S*0.05) {
    ctx.fillStyle = '#e85a7a'
    ctx.beginPath(); ctx.ellipse(0, mh*0.12, mw*0.18, mh*0.18, 0,0,Math.PI*2); ctx.fill()
  }

  // lip highlight
  ctx.fillStyle = 'rgba(255,255,255,0.28)'
  ctx.beginPath(); ctx.ellipse(-mw*0.12, -mh*0.18, mw*0.14, mh*0.12, -0.2,0,Math.PI*2); ctx.fill()

  ctx.restore()
}
