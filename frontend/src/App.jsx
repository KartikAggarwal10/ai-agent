import { useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import heroImg from './assets/hero.png'
import './App.css'
import Disply from './pages/disp_video'
function App() {
  const [count, setCount] = useState(0)

  return (
    <>
      <Disply/>
    </>
  )
}

export default App
