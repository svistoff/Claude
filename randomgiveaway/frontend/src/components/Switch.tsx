interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  hint?: string
}

export function Switch({ checked, onChange, label, hint }: SwitchProps) {
  return (
    <div className="toggle-row">
      <div>
        <div className="toggle-label">{label}</div>
        {hint && <div className="toggle-hint">{hint}</div>}
      </div>
      <button
        type="button"
        className="switch"
        data-on={checked}
        aria-pressed={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
      />
    </div>
  )
}
