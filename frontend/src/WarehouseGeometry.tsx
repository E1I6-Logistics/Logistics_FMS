// Traced from the user's 135 × 135 map.png. Units are image pixels, not metres.
// Keep physical footprints separate from labels and navigation symbols.
export const STRUCTURES = [
  { id: 'S01', x: 13.5, y: 22.5, w: 5.5, h: 5.5 },
  { id: 'S02', x: 53.5, y: 21.5, w: 5.5, h: 5.5 },
  { id: 'S03', x: 15, y: 36, w: 4, h: 4 },
  { id: 'S04', x: 54, y: 35, w: 4, h: 4 },
  { id: 'S05', x: 14.5, y: 48.5, w: 5.5, h: 5.5 },
  { id: 'S06', x: 54.5, y: 47.5, w: 5.5, h: 5.5 },
]

export const FLOOR_OUTLINE = 'M7 7 H126 V127 H7 V112 H24 V116 H28 V108 H7 V92 H24 V96 H28 V88 H7 Z'
export const RIGHT_WALL = 'M122 61 L109.5 74.5 L120 86 V88 L109 100 L120.5 113 L109.5 123'

export function WarehouseGeometry() {
  return (
    <g data-testid="warehouse-geometry">
      <path d={FLOOR_OUTLINE} fill="#F1F4F7" stroke="#8192A5" strokeWidth="0.55" strokeLinejoin="miter" />
      <path d={RIGHT_WALL} fill="none" stroke="#8192A5" strokeWidth="0.55" strokeLinejoin="miter" />
      {STRUCTURES.map(s => (
        <g key={s.id}>
          <rect x={s.x} y={s.y} width={s.w} height={s.h} fill="#F9FAFB" stroke="#9EABB9" strokeWidth="0.45" rx="0.15" />
          <path d={`M${s.x + 0.8} ${s.y + s.h / 2}h${s.w - 1.6}`} stroke="#D2D8DF" strokeWidth="0.22" />
        </g>
      ))}
    </g>
  )
}
