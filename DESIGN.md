# Design System

Outreach Campaign Manager design system. Source of truth for all UI decisions.

## Color Tokens

Uses default Tailwind palette. No custom config extensions.

| Token | Tailwind | Hex | Usage |
|-------|----------|-----|-------|
| Primary | gray-900 | #111827 | Sidebar bg, primary buttons, page titles |
| Accent | blue-600 / blue-700 hover | #2563EB / #1D4ED8 | Links, CTAs, focus rings |
| Success | green-600 | #16A34A | Verified, positive replies, won deals |
| Warning | amber-600 | #D97706 | GDPR flags, no-response states |
| Error | red-600 | #DC2626 | Bounced, negative replies, delete |
| Surface | white / gray-50 | #FFFFFF / #F9FAFB | Cards / page background |
| Border | gray-200 / gray-100 | #E5E7EB / #F3F4F6 | Card borders / row dividers |
| Text | gray-900 / gray-500 / gray-400 | -- | Primary / secondary / tertiary |
| Backdrop | black/30 | -- | Modal overlays |

### Status Colors

| Status | Color | Background |
|--------|-------|------------|
| queued | gray-600 | gray-100 |
| in_progress | blue-600 | blue-50 |
| replied_positive | green-600 | green-50 |
| replied_negative | red-600 | red-50 |
| no_response | amber-600 | amber-50 |
| bounced | red-600 | red-50 |
| active | green-600 | green-50 |
| completed | gray-600 | gray-100 |

### Metric Card Accent Borders

Left 4px border stripe on metric cards: green-400 (contacted), blue-400 (replied), yellow-400 (waiting), red-400 (error), gray-200 (default).

## Typography

| Element | Classes |
|---------|---------|
| Page title | `text-2xl font-bold text-gray-900` |
| Section header | `text-lg font-semibold text-gray-900` |
| Card label | `text-sm font-medium text-gray-500` |
| Card value | `text-2xl font-bold` |
| Body text | `text-sm text-gray-900` |
| Secondary text | `text-sm text-gray-500` |
| Helper / caption | `text-xs text-gray-500` |
| Table header | `text-xs font-medium text-gray-500 uppercase tracking-wide` |

## Spacing

| Element | Value |
|---------|-------|
| Sidebar width | `w-56` (224px) |
| Content max-width | `max-w-7xl` |
| Content padding | `px-6 py-8` |
| Section spacing | `space-y-8` |
| Grid gaps | `gap-4` |
| Card padding | `p-4` (sm), `p-5` (md), `p-6` (lg) |
| Table header cell | `px-5 py-3` |
| Table body cell | `px-5 py-4` |
| Stats grid | `grid grid-cols-2 md:grid-cols-4 gap-4` |

## Shadows & Borders

| Element | Classes |
|---------|---------|
| Card | `shadow-sm` |
| Card hover | `shadow-md` |
| Modal | `shadow-xl` |
| Card border | `border border-gray-200 rounded-xl` |
| Table border | `border border-gray-200 rounded-lg overflow-hidden` |
| Focus ring | `focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2` |

## Animation

| Pattern | Classes |
|---------|---------|
| Button transition | `transition-all duration-150` |
| Default transition | `transition-colors` |
| Button press | `active:scale-[0.98]` |
| Fade in | `animate-fade-in` |
| Modal in | `animate-modal-in` |
| Loading | `animate-spin` |
| Page enter | `animate-page-in` |

## Components

All shared components live in `frontend/src/components/ui/`.

### Button

```tsx
<Button variant="primary" size="md" loading={false} leftIcon={<Icon />}>
  Label
</Button>
```

| Variant | Style |
|---------|-------|
| primary | `bg-gray-900 text-white hover:bg-gray-800` |
| accent | `bg-blue-600 text-white hover:bg-blue-700` |
| secondary | `bg-white border border-gray-200 text-gray-700 hover:bg-gray-50` |
| danger | `bg-red-600 text-white hover:bg-red-700` |
| ghost | `text-gray-500 hover:text-gray-700 hover:bg-gray-100` |

Sizes: `sm` (px-3 py-1.5 text-xs), `md` (px-4 py-2 text-sm), `lg` (px-5 py-2.5 text-sm). All use `rounded-lg`.

### Card

```tsx
<Card accentBorder="green" hover>
  <Card.Header>Title</Card.Header>
  <Card.Body>Content</Card.Body>
  <Card.Footer>Actions</Card.Footer>
</Card>
```

Base: `bg-white rounded-xl border border-gray-200 shadow-sm`. Accent border adds a 4px left stripe. Sub-components: Header (`px-5 py-4 border-b`), Body (`p-5`), Footer (`px-5 py-3 border-t`).

### Input

```tsx
<Input label="Email" error="Required" helpText="We'll never share this" leftIcon={<Mail />} />
```

`rounded-lg border text-sm`. Focus: `ring-2 ring-blue-500`. Error: `border-red-300 ring-red-500`.

### Select

Same API as Input but for dropdowns. Custom arrow SVG, `appearance-none`, `pr-8` for arrow space.

### Modal

```tsx
<Modal open={show} onClose={close} title="Confirm" size="md">
  <Modal.Body>Are you sure?</Modal.Body>
  <Modal.Footer>
    <Button onClick={close} variant="secondary">Cancel</Button>
    <Button onClick={confirm} variant="danger">Delete</Button>
  </Modal.Footer>
</Modal>
```

Portal to document.body. Backdrop click + Escape to close. Focus trap. Sizes: sm/md/lg/xl/2xl.

### ErrorCard

```tsx
<ErrorCard message="Something went wrong" onRetry={refetch} />
```

`bg-red-50 border-red-200 rounded-xl`. AlertTriangle icon. Optional retry button.

### StatusBadge

`rounded-full px-2 py-0.5 text-xs font-medium capitalize inline-block`. 10 status-color mappings (see Status Colors above).

## Layout

```
+--sidebar(w-56)--+---main(flex-1, overflow-y-auto)---+
|  Outreach        |  ImportStatusBanner               |
|  Campaign Mgr    |  max-w-7xl mx-auto px-6 py-8      |
|                  |                                    |
|  Search...       |    Page content                    |
|  Campaigns       |                                    |
|  Today's Queue   |                                    |
|  Contacts        |                                    |
|  -------         |                                    |
|  Templates       |                                    |
|  Research        |                                    |
|  Settings        |                                    |
|                  |                                    |
|  User / Logout   |                                    |
+------------------+------------------------------------+
```

Mobile: sidebar hidden (`hidden md:flex`), hamburger menu in fixed top bar (`md:hidden`), overlay sidebar on tap.

## Tables

Container: `bg-white rounded-lg border border-gray-200 overflow-hidden`.
Header row: `bg-gray-50 border-b border-gray-200`.
Body rows: `divide-y divide-gray-100 hover:bg-gray-50 transition-colors`.

## Brand Voice in UI

- Active voice: "Scan for Replies" not "Replies can be scanned"
- Outcome-first labels: "Verified Emails" not "Email Verification Status"
- Specific numbers: "Found 3 new replies" not "Successfully updated"
- Concise CTAs: "Open Today's Queue" not "Click here to view"
- Never use: "revolutionary", "game-changing", "leverage", "synergy"
