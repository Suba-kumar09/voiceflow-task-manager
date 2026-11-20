const PALETTE = ['#2563eb', '#db2777', '#0d9488', '#7c3aed', '#ea580c', '#0891b2', '#65a30d', '#c026d3', '#475569']

function colorFor(seed: string): string {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return PALETTE[h % PALETTE.length]
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

/** Decorative: always pair with a visible name. */
export function Avatar({ name, seed, size = 32 }: { name: string; seed?: string; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-grid shrink-0 place-items-center rounded-full font-bold text-white"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.36), background: colorFor(seed ?? name) }}
    >
      {initials(name)}
    </span>
  )
}

export function Unassigned({ size = 28 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-grid shrink-0 place-items-center rounded-full border border-dashed border-control-line text-ink-faint"
      style={{ width: size, height: size, fontSize: 12 }}
    >
      –
    </span>
  )
}
