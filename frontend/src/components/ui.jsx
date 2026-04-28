export function Panel({ children, className = '', title, subtitle, accent = 'phosphor' }) {
  const accentColor = accent === 'amber' ? 'text-amber-signal' : 'text-phosphor'
  return (
    <div className={`bg-ink-800/60 border border-ink-700 relative ${className}`}>
      {(title || subtitle) && (
        <div className="px-5 py-3 border-b border-ink-700">
          {title && <div className={`mono text-[11px] tracking-widest ${accentColor}`}>{title}</div>}
          {subtitle && <div className="text-xs text-ink-400 mt-0.5">{subtitle}</div>}
        </div>
      )}
      <div className="p-5">{children}</div>
      <span className="absolute top-0 left-0 w-2 h-2 border-t border-l border-phosphor-dim opacity-60" />
      <span className="absolute top-0 right-0 w-2 h-2 border-t border-r border-phosphor-dim opacity-60" />
      <span className="absolute bottom-0 left-0 w-2 h-2 border-b border-l border-phosphor-dim opacity-60" />
      <span className="absolute bottom-0 right-0 w-2 h-2 border-b border-r border-phosphor-dim opacity-60" />
    </div>
  )
}

export function Stat({ label, value, unit, accent = 'paper' }) {
  const colors = { paper: 'text-paper', phosphor: 'text-phosphor', amber: 'text-amber-signal', alert: 'text-alert' }
  return (
    <div>
      <div className="mono text-[10px] text-ink-400 tracking-widest mb-1">{label}</div>
      <div className="flex items-baseline gap-1">
        <span className={`mono text-3xl font-bold ${colors[accent]}`}>{value}</span>
        {unit && <span className="mono text-xs text-ink-400">{unit}</span>}
      </div>
    </div>
  )
}

export function Button({ children, onClick, disabled, variant = 'primary', size = 'md' }) {
  const variants = {
    primary: 'bg-phosphor/10 border-phosphor text-phosphor hover:bg-phosphor/20',
    ghost:   'bg-transparent border-ink-500 text-ink-400 hover:border-paper hover:text-paper',
    amber:   'bg-amber-signal/10 border-amber-signal text-amber-signal hover:bg-amber-signal/20',
    alert:   'bg-alert/10 border-alert text-alert hover:bg-alert/20',
  }
  const sizes = { sm: 'px-2 py-1 text-[10px]', md: 'px-4 py-2 text-[11px]', lg: 'px-6 py-3 text-xs' }
  return (
    <button onClick={onClick} disabled={disabled}
      className={`mono tracking-widest border transition-all disabled:opacity-30 disabled:cursor-not-allowed ${variants[variant]} ${sizes[size]}`}>
      {children}
    </button>
  )
}

export function Slider({ label, value, onChange, min, max, step, unit, help }) {
  return (
    <div>
      <div className="flex justify-between items-baseline mb-2">
        <label className="mono text-[10px] text-ink-400 tracking-widest">{label}</label>
        <span className="mono text-sm text-phosphor">{value}{unit && <span className="text-ink-400 ml-1">{unit}</span>}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-phosphor" />
      {help && <div className="text-[10px] text-ink-400 mt-1">{help}</div>}
    </div>
  )
}

export function Tag({ children, color = 'phosphor' }) {
  const colors = {
    phosphor: 'border-phosphor-dim text-phosphor-dim',
    amber: 'border-amber-dim text-amber-signal',
    alert: 'border-alert text-alert',
    ink: 'border-ink-500 text-ink-400',
  }
  return <span className={`mono text-[9px] tracking-widest border px-1.5 py-0.5 ${colors[color]}`}>{children}</span>
}

export function Loading({ message = 'LOADING' }) {
  return (
    <div className="flex flex-col items-center py-12">
      <div className="w-48 h-0.5 bg-ink-700 overflow-hidden relative mb-3">
        <div className="absolute inset-0 data-stream" />
      </div>
      <div className="mono text-[11px] text-phosphor cursor-blink tracking-widest">{message}</div>
    </div>
  )
}

export function ErrorBox({ message }) {
  return (
    <div className="border border-alert/50 bg-alert/5 p-4">
      <div className="mono text-[11px] text-alert tracking-widest mb-2">✕ ERROR</div>
      <div className="text-xs text-paper font-mono">{message}</div>
      <div className="text-[10px] text-ink-400 mt-2">Ensure all backend services are running. See README for setup.</div>
    </div>
  )
}

export function Select({ label, value, onChange, options }) {
  return (
    <div>
      {label && <div className="mono text-[10px] text-ink-400 tracking-widest mb-1">{label}</div>}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="mono text-xs bg-ink-900 border border-ink-600 text-paper px-3 py-2 w-full focus:border-phosphor outline-none">
        {options.map((o) => <option key={o.value || o} value={o.value || o}>{o.label || o}</option>)}
      </select>
    </div>
  )
}
