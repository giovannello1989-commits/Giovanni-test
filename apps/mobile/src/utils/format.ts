export function formatKickoff(iso: string | Date) {
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return `${hh}:${mm}`;
}
