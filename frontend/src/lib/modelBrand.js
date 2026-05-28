// Maps a Claude model id to its DevFleet brand name (Arun / Probaho / Kiran).
// Substring match so model version bumps (e.g. a newer sonnet build) still resolve.
const BRANDS = [
  ['opus', 'Arun'],
  ['sonnet', 'Probaho'],
  ['haiku', 'Kiran'],
];

export function modelBrand(model) {
  if (!model) return '';
  const hit = BRANDS.find(([id]) => model.includes(id));
  return hit ? hit[1] : model.replace('claude-', '');
}
