# DevFleet Workstation — Hardware UI Kit + Global Config

**Status:** Spec written 2026-05-27, post-Phase-4 workstation iteration. Next session implements.

## Why this exists

DevFleet's Dashboard + MissionBoard already use the workstation pattern (ws-toolbar, ws-heading, RAG status, mono buttons). It looks engineering-grade. Next level: the UI should feel like a **physical control panel** — switches, knobs, dials, raised-button feedback — with a single global config controlling every visual token.

## Aesthetic direction

Reference: Bloomberg Terminal × audio mixing console × NASA mission-control hardware. Skeuomorphic enough that interactive elements feel TACTILE without crossing into kitsch. Buttons feel pressed when active. Toggles feel like real switches. Dials/knobs feel rotational.

## Components to build

### 1. Buttons — physical-button feel
- **Idle:** subtle raised effect (gradient top-light + drop shadow + dark bottom edge)
- **Hover:** brighter top highlight, slightly more lift
- **:active / pressed:** `transform: translateY(2px)` + inset box-shadow → looks pushed in
- **Selected/active state (e.g. active nav item):** PERMANENTLY pressed-in (recessed) so you can tell at a glance which is the current page
- Variants: `primary` (amber filled, glow halo), `ghost` (transparent), `danger` (red ghost), `ghost-g` (green ghost for ship/complete)
- Sharp corners always — no radius

### 2. Toggle switch — `.ws-switch`
Hardware-rocker style. Like a real toggle on an amp. Two states (off | on) with a tactile slide between. Use for boolean settings: auto_dispatch on/off, schedule_enabled, etc.

### 3. Knob / rotary — `.ws-knob`
For numeric ranges (1–N max_agents per lane, priority 0–10). SVG-based, with tick marks around the circumference. Dragging vertically or scrolling rotates it. Center label shows current value.

### 4. Segment / radio group — `.ws-segment`
For exclusive picks (mission_type, model tier). Looks like a row of hardware buttons where exactly one is depressed. Replaces stock `<select>` for short option lists.

### 5. Status LED — `.ws-led`
Tiny indicator dot, RAG-colored, optional pulse for "running". Replaces the various per-component status circles scattered through the app.

### 6. Bar meter — `.ws-meter`
For lane capacity (used/total), agent slots, cost budgets. Stepped (not smooth) so it looks like a discrete LED level meter on hardware.

### 7. Toggle bank — `.ws-toggle-bank`
A row of small LED-labeled switches. For: "show chat turns", "include archived", "auto-refresh".

## Global config — design tokens

**Single source of truth for every visual axis.** Centralize in:

`frontend/src/design/tokens.css` (imported by index.css at top)

```css
:root {
  /* Brand */
  --brand-mark: #d4a017;
  --brand-mark-hot: #e8b820;
  --brand-mark-soft: rgba(212, 160, 23, 0.12);

  /* RAG — state only */
  --rag-g: #6ea358; --rag-g-soft: rgba(110, 163, 88, 0.12);
  --rag-a: #d4a017; --rag-a-soft: rgba(212, 160, 23, 0.12);
  --rag-r: #d36359; --rag-r-soft: rgba(211, 99, 89, 0.12);

  /* Surface (dark) — five tiers from deepest bg → elevated */
  --surf-0: #09090b;
  --surf-1: #0f0f13;
  --surf-2: #18181b;
  --surf-3: #1e1e23;
  --surf-4: #27272a;

  /* Ink (text) */
  --ink-0: #fafafa;
  --ink-1: #a1a1aa;
  --ink-2: #71717a;
  --ink-3: #52525b;

  /* Edges — hardware looks need stronger borders */
  --edge-1: rgba(255,255,255,0.06);
  --edge-2: rgba(255,255,255,0.12);
  --edge-3: rgba(255,255,255,0.22);

  /* Hardware depth — used by buttons, switches, knobs */
  --bevel-top:    rgba(255, 255, 255, 0.08);  /* top-highlight = light from above */
  --bevel-bottom: rgba(0, 0, 0, 0.45);        /* bottom-shadow = grounded edge */
  --shadow-raised: 0 1px 0 var(--bevel-top) inset, 0 2px 4px rgba(0,0,0,0.4);
  --shadow-pressed: 0 2px 4px rgba(0,0,0,0.5) inset, 0 1px 0 rgba(255,255,255,0.02);
  --shadow-glow-amber: 0 0 14px rgba(212, 160, 23, 0.4);

  /* Type — fluid scale via clamp() */
  --fs-micro:  clamp(10px, 0.45vw + 7.5px, 11.5px);
  --fs-body:   clamp(12px, 0.85vw + 7px, 14px);
  --fs-h3:     clamp(13px, 0.7vw + 10px, 16px);
  --fs-h2:     clamp(15px, 0.85vw + 11px, 20px);
  --fs-h1:     clamp(26px, 3.6vw + 4px, 60px);
  --fs-kpi:    clamp(26px, 3.5vw + 8px, 52px);

  /* Spacing scale (4px base) */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px; --sp-8: 64px;

  /* Motion */
  --t-fast: 80ms;
  --t-base: 150ms;
  --t-slow: 300ms;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);

  /* Fonts */
  --font-mono: 'JetBrains Mono', 'SF Mono', monospace;
  --font-display: 'Space Mono', var(--font-mono);
}
```

Every component in the workstation references these — **never hard-coded colors / sizes / shadows again**. A future palette swap (light theme, alt-brand) is one block of token edits.

## Implementation order

1. **Extract tokens** — move all CSS variables in index.css into `design/tokens.css`. Add new hardware-depth tokens. Audit and replace remaining hard-coded colors in components.
2. **Build `.ws-btn` 3D variant** — gradient + bevel + drop shadow + :active translate. Apply to existing ws-btn / ws-btn--primary / ws-btn--danger / ws-btn--ghost-g.
3. **Nav items** — sidebar nav becomes raised + recessed-when-active.
4. **Switch** — `<Switch>` React component using a single SVG. Wire into Mission auto_dispatch / schedule_enabled.
5. **Knob** — `<Knob>` for lane max_agents in Fleet Config.
6. **Segment** — replace mission_type `<select>` with segmented button group.
7. **Meter + LED** — small atoms, wire into lane capacity + status indicators across the app.

## Scope boundaries — DO NOT in this phase

- No JS animation libs (framer-motion etc) — CSS only, hardware feel comes from shadows + transforms
- No icon-pack swap (current Heroicons are fine)
- No theme switcher — stay dark-only for now
- No keyboard-shortcut rework — already wired in Dashboard
- No backend changes
- Do not touch StatusPage, ProjectBot, ProjectDetail yet — get the kit solid first, then apply

## Verification gates

- `npm run build` clean
- All buttons have visible :active feedback (press in)
- Sidebar Dashboard item looks recessed when active (vs raised when idle)
- At least one Switch, Knob, and Segment in production use
- Zero hard-coded `#hex` colors outside tokens.css (grep check)
- Responsive: 320px phone → 1920px desktop, all components fluid
