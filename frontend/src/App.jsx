import { useState, useEffect } from 'react'
import Topology from './components/Topology.jsx'
import Subscribers from './components/Subscribers.jsx'
import CallFlow from './components/CallFlow.jsx'
import Failures from './components/Failures.jsx'
import ErrorCodes from './components/ErrorCodes.jsx'
import Scenarios from './components/Scenarios.jsx'
import Telemetry from './components/Telemetry.jsx'
import MLView from './components/MLView.jsx'
import Agent from './components/Agent.jsx'

const MODULES = [
  { id: 'topology',    label: 'TOPOLOGY',    glyph: '◈', desc: '5G core mesh' },
  { id: 'subscribers', label: 'SUBSCRIBERS', glyph: '◯', desc: 'UE simulator' },
  { id: 'callflow',    label: 'CALL FLOW',   glyph: '⇄', desc: 'Sequence diagrams' },
  { id: 'failures',    label: 'FAILURES',    glyph: '⚠', desc: 'Chaos injection' },
  { id: 'errorcodes',  label: 'ERROR CODES', glyph: '⚡', desc: '5G cause codes + ML' },
  { id: 'scenarios',   label: 'SCENARIOS',   glyph: '▶', desc: 'Failure library' },
  { id: 'telemetry',   label: 'TELEMETRY',   glyph: '≡', desc: 'Logs & metrics' },
  { id: 'ml',          label: 'ML ENGINE',   glyph: '▲', desc: 'Anomaly detection' },
  { id: 'agent',       label: 'LLM AGENT',   glyph: '◉', desc: 'Claude SRE' },
]

export default function App() {
  const [active, setActive] = useState('topology')
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="min-h-screen flex flex-col scanlines">
      <header className="border-b border-ink-700 bg-ink-900/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="max-w-[1800px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-phosphor animate-pulse-slow" />
              <span className="mono text-phosphor text-sm font-bold tracking-widest">
                5G<span className="text-paper">.AIOPS</span>
              </span>
            </div>
            <span className="mono text-[10px] text-ink-400 tracking-wider hidden sm:inline">
              v1.0 · NF SIMULATOR + LLM SRE
            </span>
          </div>
          <div className="mono text-[11px] text-ink-400 flex items-center gap-4">
            <span>{time.toISOString().split('T')[1].split('.')[0]} UTC</span>
          </div>
        </div>
      </header>

      <div className="flex flex-1 max-w-[1800px] mx-auto w-full">
        <nav className="w-56 border-r border-ink-700 bg-ink-900/50 py-6 px-3 shrink-0">
          <div className="mono text-[10px] text-ink-400 tracking-widest px-3 mb-3">MODULES</div>
          {MODULES.map((m) => (
            <button key={m.id} onClick={() => setActive(m.id)}
              className={`w-full text-left px-3 py-3 mb-1 transition-all border-l-2 ${
                active === m.id ? 'border-phosphor bg-ink-800/80' : 'border-transparent hover:border-ink-500 hover:bg-ink-800/40'
              }`}>
              <div className="flex items-center gap-3">
                <span className={`mono text-lg ${active === m.id ? 'text-phosphor' : 'text-ink-400'}`}>{m.glyph}</span>
                <div>
                  <div className={`mono text-xs tracking-wider ${active === m.id ? 'text-paper' : 'text-ink-400'}`}>{m.label}</div>
                  <div className="text-[10px] text-ink-400">{m.desc}</div>
                </div>
              </div>
            </button>
          ))}

          <div className="mono text-[10px] text-ink-400 tracking-widest px-3 mt-8 mb-3">5G CORE NFs</div>
          <div className="px-3 text-[10px] mono space-y-1 text-ink-400">
            {['NRF · 8001', 'AUSF · 8002', 'UDM · 8003', 'AMF · 8004', 'SMF · 8005', 'UPF · 8006', 'PCF · 8007'].map((n) => (
              <div key={n} className="flex justify-between"><span>{n.split(' · ')[0]}</span><span className="text-paper">:{n.split(' · ')[1]}</span></div>
            ))}
          </div>
        </nav>

        <main className="flex-1 p-6 md:p-8 overflow-x-hidden">
          <div key={active} className="animate-fade-in">
            {active === 'topology' && <Topology />}
            {active === 'subscribers' && <Subscribers />}
            {active === 'callflow' && <CallFlow />}
            {active === 'failures' && <Failures />}
            {active === 'errorcodes' && <ErrorCodes />}
            {active === 'scenarios' && <Scenarios />}
            {active === 'telemetry' && <Telemetry />}
            {active === 'ml' && <MLView />}
            {active === 'agent' && <Agent />}
          </div>
        </main>
      </div>

      <footer className="border-t border-ink-700 px-6 py-3 mono text-[10px] text-ink-400 tracking-wider flex justify-between">
        <span>5G.AIOPS // FASTAPI × CLAUDE × SCIKIT-LEARN × REACT</span>
        <span>SIMULATED 5G CORE — NOT FOR PRODUCTION</span>
      </footer>
    </div>
  )
}
