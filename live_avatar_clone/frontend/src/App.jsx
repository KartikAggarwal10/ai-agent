import { useEffect, useRef, useState } from 'react'
import AvatarCanvas from './components/AvatarCanvas.jsx'
import { useAudioAnalyzer } from './hooks/useAudioAnalyzer.js'

const VOICE_FALLBACK = [
  { id:'en-US-AriaNeural', label:'Aria — warm sweet girl' },
  { id:'en-US-JennyNeural', label:'Jenny — bubbly girl' },
  { id:'en-IN-NeerjaNeural', label:'Neerja — Indian girl' },
  { id:'en-GB-SoniaNeural', label:'Sonia — British girl' },
]

export default function App(){
  const [status, setStatus] = useState('idle') // idle | listening | thinking | speaking
  const [persona, setPersona] = useState('You are warm, playful, a little shy and very caring. You love the user and remember they are special to you.')
  const [voice, setVoice] = useState('en-US-AriaNeural')
  const [voices, setVoices] = useState(VOICE_FALLBACK)
  const [chat, setChat] = useState([
    { role:'miko', text:'Hii! I\'m Miko — your little companion ♡\nTap the mic and talk to me — watch my lips move when I reply!' }
  ])
  const [input, setInput] = useState('')
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)

  const audioRef = useRef(null)
  const analyzer = useAudioAnalyzer()
  const wsRef = useRef(null)
  const recogRef = useRef(null)
  const chatEndRef = useRef(null)

  // fetch voices + connect ws
  useEffect(()=>{
    fetch('/api/voices').then(r=>r.json()).then(d=>{ if(d.voices?.length) setVoices(d.voices)}).catch(()=>{})
    connectWS()
    return ()=>{ try{ wsRef.current?.close()}catch{} }
  },[])

  function connectWS(){
    const proto = location.protocol==='https:'?'wss:':'ws:'
    const url = `${proto}//${location.host}/ws`
    // in vite dev, host is 5173 so fallback to 8000
    const wsUrl = location.port==='5173' ? 'ws://localhost:8000/ws' : url
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.onopen = ()=> ws.send(JSON.stringify({type:'config', persona, voice}))
    ws.onmessage = async (e)=>{
      const msg = JSON.parse(e.data)
      if(msg.type==='reply'){
        setChat(c=>[...c, {role:'miko', text: msg.text}])
        setStatus('speaking')
        if(msg.audio_b64){
          await playAudio(msg.audio_b64, msg.mime)
        } else {
          // fallback: browser TTS
          browserSpeak(msg.text)
        }
      } else if(msg.type==='thinking'){ setStatus('thinking') }
      else if(msg.type==='ready'){ if(msg.voices) setVoices(msg.voices) }
    }
    ws.onclose = ()=> setTimeout(connectWS, 2000)
  }

  useEffect(()=>{ chatEndRef.current?.scrollIntoView({behavior:'smooth'}) },[chat, status])

  // send persona/voice updates
  useEffect(()=>{
    if(wsRef.current?.readyState===1) wsRef.current.send(JSON.stringify({type:'config', persona, voice}))
  },[persona, voice])

  async function playAudio(b64, mime){
    try{
      const blob = b64ToBlob(b64, mime||'audio/mpeg')
      const url = URL.createObjectURL(blob)
      const a = audioRef.current
      a.src = url
      a.onplay = ()=>{ setSpeaking(true); analyserAttach() }
      a.onended = a.onpause = ()=>{ setSpeaking(false); setStatus('idle'); URL.revokeObjectURL(url) }
      a.onerror = ()=>{ setSpeaking(false); setStatus('idle') }
      analyserAttach()
      await a.play()
    }catch(e){ console.warn(e); setSpeaking(false); setStatus('idle') }
  }
  function analyserAttach(){
    if(audioRef.current) analyzer.attach(audioRef.current)
  }

  function browserSpeak(text){
    if(!('speechSynthesis' in window)) { setStatus('idle'); return }
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    // pick a female voice
    const vs = window.speechSynthesis.getVoices()
    const fem = vs.find(v=>/female|aria|jenny|sonia|neerja|natasha|zira/i.test(v.name)) || vs[0]
    if(fem) u.voice = fem
    u.rate = 1.02; u.pitch = 1.08
    // fake analyser volume from speechSynthesis (no real audio node) — drive mouth via timer
    let t=0, iv
    u.onstart = ()=>{ setSpeaking(true); setStatus('speaking')
      iv = setInterval(()=>{
        // generate fake volume envelope that looks like speech
        const fakeVol = 0.35 + Math.sin(t*0.35)*0.2 + Math.random()*0.25
        const fakeVis = [0,1,2,3,4][Math.floor(Math.random()*5)]
        // feed into analyser hook via monkey: override getMetrics temporarily
        t++
      }, 60)
      // hijack getMetrics to return fake data
      const orig = analyzer.getMetrics
      analyzer.getMetrics = ()=>({ volume: 0.45 + Math.sin(t*0.4)*0.2 + Math.random()*0.25, viseme: [1,2,3,1,2,4][t%6], bands:[0,0,0] })
      u._origGet = orig; u._iv = iv
    }
    const cleanup = ()=>{
      clearInterval(u._iv)
      if(u._origGet) analyzer.getMetrics = u._origGet
      setSpeaking(false); setStatus('idle')
    }
    u.onend = cleanup; u.onerror = cleanup; u.onpause = cleanup
    window.speechSynthesis.speak(u)
  }

  function sendText(text){
    const t = (text||input).trim()
    if(!t) return
    setChat(c=>[...c, {role:'you', text:t}])
    setInput('')
    setStatus('thinking')
    // try ws, else direct http
    if(wsRef.current?.readyState===1){
      wsRef.current.send(JSON.stringify({type:'user_text', text:t}))
    } else {
      fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({text:t, persona, voice, history: chat.slice(-6).map(m=>({role: m.role==='you'?'user':'assistant', content:m.text}))})
      }).then(r=>r.json()).then(async d=>{
        setChat(c=>[...c, {role:'miko', text:d.reply}])
        if(d.audio_b64) await playAudio(d.audio_b64, d.mime)
        else browserSpeak(d.reply)
      }).catch(()=>{ setStatus('idle'); setChat(c=>[...c,{role:'miko', text:"Oops — backend not reachable. Is it running on :8000? I'm still here though!"}]) })
    }
  }

  // voice input
  function toggleListen(){
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if(!SR){ alert('Voice input needs Chrome or Edge on desktop. You can still type!'); return }
    if(listening){
      try{ recogRef.current?.stop() }catch{}
      setListening(false); setStatus('idle'); return
    }
    const rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.continuous = false
    recogRef.current = rec
    rec.onstart = ()=>{ setListening(true); setStatus('listening') }
    rec.onend = ()=>{ setListening(false); setStatus(s=> s==='listening'?'idle':s) }
    rec.onerror = ()=>{ setListening(false); setStatus('idle') }
    rec.onresult = e=>{
      const txt = e.results?.[0]?.[0]?.transcript || ''
      if(txt.trim()) sendText(txt.trim())
    }
    rec.start()
  }

  function stopSpeaking(){
    try{ audioRef.current?.pause(); audioRef.current.currentTime=0 }catch{}
    try{ window.speechSynthesis.cancel() }catch{}
    setSpeaking(false); setStatus('idle')
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">♡</span>
          <div>
            <div className="brand-name">Miko</div>
            <div className="brand-sub">your live girl avatar — talks with real lip-sync</div>
          </div>
        </div>
        <div className="top-actions">
          <span className={`live-dot ${speaking?'live': status==='listening'?'listen':''}`} />
          <span className="live-text">{speaking?'LIVE • speaking': status==='listening'?'● listening': status==='thinking'?'thinking…':'ready'}</span>
        </div>
      </header>

      <main className="layout">
        <section className="stage">
          <AvatarCanvas analyserHook={analyzer} audioRef={audioRef} speaking={speaking} status={status} />
          <audio ref={audioRef} crossOrigin="anonymous" playsInline hidden />

          <div className="controls-row">
            <button className={`mic-btn ${listening?'on':''} ${speaking?'busy':''}`} onClick={toggleListen} title="Tap to talk">
              <span className="mic-icon">{listening?'■':'🎙'}</span>
              {listening ? 'Tap to stop' : 'Tap to talk'}
            </button>
            {speaking && <button className="stop-btn" onClick={stopSpeaking}>Stop</button>}
            <select className="voice-select" value={voice} onChange={e=>setVoice(e.target.value)} title="Her voice">
              {voices.map(v=> <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
          </div>
          <div className="hint">Tip: Allow microphone. She will lip-sync to every word — no photo needed, no GPU, totally free.</div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h3>Chat</h3>
            <span className="panel-sub">Type or use voice — Miko replies with voice + lips</span>
          </div>

          <div className="persona-box">
            <label>Her personality (edit to change how she talks)</label>
            <textarea value={persona} onChange={e=>setPersona(e.target.value)} rows={2} placeholder="Describe Miko's personality..." />
          </div>

          <div className="messages">
            {chat.map((m,i)=>(
              <div key={i} className={`bubble ${m.role}`}>
                <div className="bubble-role">{m.role==='you'?'You':'Miko ♡'}</div>
                <div className="bubble-text">{m.text}</div>
              </div>
            ))}
            {status==='thinking' && <div className="typing"><span/><span/><span/></div>}
            <div ref={chatEndRef} />
          </div>

          <div className="composer">
            <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=> e.key==='Enter' && sendText()} placeholder="Say something to Miko… (Enter to send)" />
            <button className="send-btn" onClick={()=>sendText()} disabled={!input.trim()}>Send</button>
            <button className="send-voice-btn" onClick={toggleListen} title="Voice input">{listening?'■':'🎙'}</button>
          </div>
        </section>
      </main>

      <footer className="foot">Runs on your i3 CPU. No GPU, no payments, no photo upload. Free voices via edge-tts + free LLM via Pollinations/Ollama. Lip-sync is real audio-driven visemes at 60fps.</footer>
    </div>
  )
}

function b64ToBlob(b64, mime){
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i)
  return new Blob([arr], {type:mime})
}
