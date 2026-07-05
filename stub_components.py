"""
stub_components.py
==================
Writes all 10 stub components to:
  E:\\PowerAcademy\\app\\poweracademy\\src\\components\\

Components:
  CRM.js            — Deal / contact relationship tracker
  Sponsors.js       — PE / infra sponsor coverage universe
  MandAScreen.js    — M&A screening tool
  CompsLibrary.js   — Comparable companies / precedent transactions library
  PitchTracker.js   — Live pitch / mandate tracker
  ReadingLog.js     — Books read log synced to Library tab
  Calendar.js       — Coverage calendar (earnings, rate case decisions, NDRs)
  WeeklyDebrief.js  — Weekly self-review / MD prep journal
  CRM (already listed above)

Each stub is a clean, functional placeholder with:
  - Proper import/export
  - Dark-mode styling consistent with Power Academy palette
  - A clear "Coming Soon" skeleton with planned feature list
  - Zero broken imports (no FMP, no missing deps)

Usage:
  python stub_components.py
"""

import os
from pathlib import Path

APP_SRC    = Path(r"E:\PowerAcademy\app\poweracademy\src")
COMPONENTS = APP_SRC / "components"

# ── Shared style constants (embedded in each component) ───────────────────────
STYLE_PREAMBLE = '''
const S = {
  page: {
    padding: 28, color: '#e2e8f0', fontFamily: 'Inter, sans-serif',
    background: '#0f172a', minHeight: '100%',
  },
  title: { fontSize: 22, fontWeight: 700, color: '#f1f5f9', marginBottom: 6 },
  subtitle: { fontSize: 14, color: '#64748b', marginBottom: 28 },
  card: {
    background: '#1e293b', borderRadius: 10, padding: '18px 20px',
    marginBottom: 16, border: '1px solid #334155',
  },
  cardTitle: { fontSize: 14, fontWeight: 600, color: '#94a3b8', marginBottom: 10 },
  pill: (active) => ({
    display: 'inline-block', padding: '3px 10px', borderRadius: 20, fontSize: 12,
    background: active ? '#0c4a6e' : '#1e293b',
    color: active ? '#38bdf8' : '#64748b',
    border: `1px solid ${active ? '#0369a1' : '#334155'}`,
    marginRight: 6, marginBottom: 6, cursor: 'pointer',
  }),
  coming: {
    background: '#0f172a', border: '1px dashed #334155',
    borderRadius: 10, padding: '32px 24px', textAlign: 'center',
    color: '#475569', fontSize: 14, marginBottom: 16,
  },
  featureList: {
    listStyle: 'none', padding: 0, margin: '16px 0 0',
    textAlign: 'left', display: 'inline-block',
  },
  feature: { color: '#64748b', fontSize: 13, padding: '3px 0' },
};
'''

# ── Component definitions ─────────────────────────────────────────────────────
STUBS = {}

STUBS["CRM.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const CONTACTS = [
  { company: 'NextEra Energy', name: 'Kirk Crews', title: 'CFO', last: '2026-05-12', status: 'Warm' },
  { company: 'Dominion Energy', name: 'Steve Ridge', title: 'Treasurer', last: '2026-04-30', status: 'Active' },
  { company: 'Entergy', name: 'Kimberly Fontenot', title: 'VP IR', last: '2026-03-18', status: 'Cold' },
];

const STATUS_COLOR = { Active: '#14532d', Warm: '#1e3a5f', Cold: '#1e293b' };

export default function CRM() {
  const [filter, setFilter] = useState('All');
  const statuses = ['All', 'Active', 'Warm', 'Cold'];
  const filtered = filter === 'All' ? CONTACTS : CONTACTS.filter(c => c.status === filter);

  return (
    <div style={S.page}>
      <div style={S.title}>CRM — Coverage Contacts</div>
      <div style={S.subtitle}>Track relationships across 23 coverage companies + PE sponsors</div>

      <div style={{ marginBottom: 20 }}>
        {statuses.map(s => (
          <span key={s} style={S.pill(filter === s)} onClick={() => setFilter(s)}>{s}</span>
        ))}
      </div>

      {filtered.map((c, i) => (
        <div key={i} style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{c.name}</span>
              <span style={{ color: '#64748b', fontSize: 13, marginLeft: 8 }}>{c.title}</span>
            </div>
            <span style={{
              fontSize: 11, background: STATUS_COLOR[c.status] || '#1e293b',
              color: '#94a3b8', padding: '2px 8px', borderRadius: 4,
            }}>{c.status}</span>
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
            {c.company} \u00b7 Last contact: {c.last}
          </div>
        </div>
      ))}

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Full CRM — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Add / edit contacts inline', 'Call notes with date stamps', 'Deal linkage per contact',
            'Email draft launcher', 'Last-touch reminders', 'Supabase sync'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["Sponsors.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const SPONSORS = [
  { name: 'Brookfield Asset Management', aum: '$900B', focus: 'Renewables, Transmission', deals: 4 },
  { name: 'KKR', aum: '$550B', focus: 'Power Generation, Infra', deals: 3 },
  { name: 'Blackstone Infrastructure', aum: '$320B', focus: 'Utilities, Midstream', deals: 2 },
  { name: 'Global Infrastructure Partners', aum: '$100B', focus: 'Power, Water, Transport', deals: 2 },
  { name: 'I Squared Capital', aum: '$40B', focus: 'Contracted Power, Renewables', deals: 1 },
  { name: 'Stonepeak', aum: '$70B', focus: 'Power, Digital Infra', deals: 1 },
  { name: 'ArcLight Capital', aum: '$24B', focus: 'Energy Transition', deals: 1 },
];

export default function Sponsors() {
  return (
    <div style={S.page}>
      <div style={S.title}>PE / Infra Sponsor Universe</div>
      <div style={S.subtitle}>7 sponsors tracked \u00b7 Linked to deal history in M&A Screen</div>

      {SPONSORS.map((sp, i) => (
        <div key={i} style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{sp.name}</div>
            <div style={{ color: '#94a3b8', fontSize: 13 }}>{sp.aum} AUM</div>
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
            {sp.focus} \u00b7 {sp.deals} deal{sp.deals !== 1 ? 's' : ''} in coverage universe
          </div>
        </div>
      ))}

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Full Sponsor Placemat — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Portfolio company mapping', 'Fund vintage & dry powder', 'Key partner contacts',
            'Recent deal history', 'Return profile / target IRR', 'Link to CompanyIntel'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["MandAScreen.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const DEALS = [
  { date: '2025-11', target: 'Puget Sound Energy', acquirer: 'Hydro One / PSP', value: '$9.4B', status: 'Rumored' },
  { date: '2025-08', target: 'Hawaiian Electric', acquirer: 'Undisclosed', value: 'TBD', status: 'Exploring' },
  { date: '2024-06', target: 'PPL Rhode Island', acquirer: 'NiSource', value: '$1.05B', status: 'Closed' },
  { date: '2024-01', target: 'Louisville Gas & Electric', acquirer: 'PPL Corp', value: 'Internal', status: 'Closed' },
];

const STATUS_COLOR = { Closed: '#14532d', Exploring: '#1e3a5f', Rumored: '#4a1d1d' };

export default function MandAScreen() {
  return (
    <div style={S.page}>
      <div style={S.title}>M&A Screen</div>
      <div style={S.subtitle}>
        Utility M&A deal tracker \u00b7 Coverage universe + broader sector
      </div>

      {DEALS.map((d, i) => (
        <div key={i} style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{d.target}</span>
              <span style={{ color: '#64748b', fontSize: 13, margin: '0 6px' }}>\u2190</span>
              <span style={{ color: '#94a3b8', fontSize: 13 }}>{d.acquirer}</span>
            </div>
            <span style={{
              fontSize: 11, background: STATUS_COLOR[d.status] || '#1e293b',
              color: '#94a3b8', padding: '2px 8px', borderRadius: 4,
            }}>{d.status}</span>
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
            {d.date} \u00b7 {d.value}
          </div>
        </div>
      ))}

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Full M&A Screen — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['EV/EBITDA multiples by deal', 'Rate base premium analysis', 'Regulatory approval tracker',
            'Precedent transaction comps table', 'Synergy analysis', 'Export to Excel'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["CompsLibrary.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const CATEGORIES = ['All', 'Electric Utility', 'IPP', 'Water Utility', 'Transmission'];

export default function CompsLibrary() {
  const [cat, setCat] = useState('All');

  return (
    <div style={S.page}>
      <div style={S.title}>Comps Library</div>
      <div style={S.subtitle}>
        Trading comps + precedent transactions \u00b7 23 coverage companies
      </div>

      <div style={{ marginBottom: 20 }}>
        {CATEGORIES.map(c => (
          <span key={c} style={S.pill(cat === c)} onClick={() => setCat(c)}>{c}</span>
        ))}
      </div>

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Comps Library — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Live trading multiples (EV/EBITDA, P/E, P/B)', 'Rate base premium screen',
            'Dividend yield comp set', 'Precedent transaction table with filters',
            'CapIQ-powered data refresh', 'Export to Excel / pitch template'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["PitchTracker.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const PITCHES = [
  { company: 'NextEra Energy', type: 'Rate Case Advisory', stage: 'Pitch Sent', date: '2026-06-10' },
  { company: 'Eversource', type: 'M&A Advisory', stage: 'Follow-up', date: '2026-05-22' },
  { company: 'Evergy', type: 'Equity Offering', stage: 'Won', date: '2026-04-15' },
];

const STAGE_COLOR = {
  'Won': '#14532d', 'Pitch Sent': '#1e3a5f', 'Follow-up': '#4a1d96',
  'Lost': '#4a1d1d', 'Idea': '#1e293b',
};

export default function PitchTracker() {
  return (
    <div style={S.page}>
      <div style={S.title}>Pitch Tracker</div>
      <div style={S.subtitle}>Live mandate & pitch pipeline across PUR coverage</div>

      {PITCHES.map((p, i) => (
        <div key={i} style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{p.company}</span>
              <span style={{ color: '#64748b', fontSize: 13, marginLeft: 8 }}>{p.type}</span>
            </div>
            <span style={{
              fontSize: 11, background: STAGE_COLOR[p.stage] || '#1e293b',
              color: '#94a3b8', padding: '2px 8px', borderRadius: 4,
            }}>{p.stage}</span>
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>{p.date}</div>
        </div>
      ))}

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Full Pitch Tracker — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Stage funnel view (Kanban)', 'Revenue & fee tracking', 'Team member assignment',
            'Next action reminders', 'Win/loss analysis by product type',
            'Link to CRM contacts'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["ReadingLog.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
export default function ReadingLog() {
  return (
    <div style={S.page}>
      <div style={S.title}>Reading Log</div>
      <div style={S.subtitle}>
        Track books read from the Library \u00b7 Notes, ratings, and key takeaways
      </div>
      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Reading Log — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Books read log linked to Library tab', 'Date started / finished', 'Rating (1\u20135)',
            'Key takeaways (free text)', 'Quote capture', 'Supabase sync across devices',
            'Progress bar per book'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["CalendarView.js"] = '''import React, { useState } from 'react';
''' + STYLE_PREAMBLE + '''
const EVENTS = [
  { date: '2026-07-08', company: 'NEE', type: 'Earnings', desc: 'Q2 2026 Earnings Call' },
  { date: '2026-07-14', company: 'D', type: 'Rate Case', desc: 'VA SCC Decision — EVA rate case' },
  { date: '2026-07-22', company: 'ETR', type: 'Earnings', desc: 'Q2 2026 Earnings Call' },
  { date: '2026-08-05', company: 'PCG', type: 'NDR', desc: 'Non-deal roadshow — NYC' },
  { date: '2026-09-10', company: 'AEE', type: 'Conference', desc: 'EEI Financial Conference' },
];

const TYPE_COLOR = {
  'Earnings': '#0c4a6e', 'Rate Case': '#14532d', 'NDR': '#4a1d96', 'Conference': '#1e3a5f',
};

export default function CalendarView() {
  return (
    <div style={S.page}>
      <div style={S.title}>Coverage Calendar</div>
      <div style={S.subtitle}>Earnings, rate case decisions, NDRs, and conferences</div>

      {EVENTS.map((e, i) => (
        <div key={i} style={S.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{e.company}</span>
              <span style={{ color: '#94a3b8', fontSize: 13, marginLeft: 8 }}>{e.desc}</span>
            </div>
            <span style={{
              fontSize: 11, background: TYPE_COLOR[e.type] || '#1e293b',
              color: '#94a3b8', padding: '2px 8px', borderRadius: 4,
            }}>{e.type}</span>
          </div>
          <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>{e.date}</div>
        </div>
      ))}

      <div style={S.coming}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Full Calendar — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Auto-pull earnings dates from EDGAR', 'Rate case decision date tracker',
            'Google Calendar sync', 'Email / alert reminders', 'Month/week toggle view',
            'Filter by company or event type'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

STUBS["WeeklyDebrief.js"] = '''import React, { useState, useEffect } from 'react';
''' + STYLE_PREAMBLE + '''
const PROMPTS = [
  'What were your 3 biggest wins this week?',
  'Where did you add the most client value?',
  'What knowledge gap surfaced that you need to close?',
  'What would an MD have done differently?',
  'What\u2019s your #1 priority for next week?',
];

export default function WeeklyDebrief() {
  const [answers, setAnswers] = useState(() =>
    PROMPTS.reduce((acc, p) => ({ ...acc, [p]: '' }), {})
  );
  const [saved, setSaved] = useState(false);

  const handleChange = (prompt, val) => {
    setAnswers(prev => ({ ...prev, [prompt]: val }));
    setSaved(false);
  };

  const handleSave = () => {
    // TODO: sync to Supabase
    console.log('Weekly debrief:', answers);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const week = (() => {
    const now = new Date();
    const jan1 = new Date(now.getFullYear(), 0, 1);
    return Math.ceil((((now - jan1) / 86400000) + jan1.getDay() + 1) / 7);
  })();

  return (
    <div style={S.page}>
      <div style={S.title}>Weekly Debrief</div>
      <div style={S.subtitle}>MD Prep \u00b7 Week {week}, {new Date().getFullYear()}</div>

      {PROMPTS.map((prompt, i) => (
        <div key={i} style={S.card}>
          <div style={S.cardTitle}>{prompt}</div>
          <textarea
            value={answers[prompt]}
            onChange={e => handleChange(prompt, e.target.value)}
            placeholder="Write your reflection\u2026"
            rows={3}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: '#0f172a', border: '1px solid #334155',
              borderRadius: 6, color: '#e2e8f0', fontSize: 14,
              padding: '8px 10px', resize: 'vertical', fontFamily: 'inherit',
            }}
          />
        </div>
      ))}

      <button
        onClick={handleSave}
        style={{
          background: saved ? '#14532d' : '#0369a1',
          color: '#fff', border: 'none', borderRadius: 8,
          padding: '10px 24px', fontSize: 14, fontWeight: 600,
          cursor: 'pointer', transition: 'background 0.2s',
        }}
      >
        {saved ? '\u2713 Saved' : 'Save Debrief'}
      </button>

      <div style={{ ...S.coming, marginTop: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 8 }}>
          Enhancements — Coming Soon
        </div>
        <ul style={S.featureList}>
          {['Supabase persistence (history by week)', 'Prior weeks review / search',
            'AI feedback on answers vs MD benchmark', 'Export to PDF for performance review',
            'Streak tracker'].map(f => (
            <li key={f} style={S.feature}>\u2022 {f}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
'''

# ── Write all stubs ───────────────────────────────────────────────────────────
print(f"Writing {len(STUBS)} stub components to: {COMPONENTS}\n")

try:
    COMPONENTS.mkdir(parents=True, exist_ok=True)
    can_write = True
except Exception as e:
    print(f"WARNING: Cannot create directory at {COMPONENTS}: {e}")
    print("Writing to script directory as fallback.\n")
    COMPONENTS = Path(__file__).parent
    can_write = True

results = []
for filename, content in STUBS.items():
    path = COMPONENTS / filename
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.lstrip('\n'))
        size = len(content)
        results.append((filename, True, size))
        print(f"  \u2713 {filename} ({size:,} chars)")
    except Exception as e:
        results.append((filename, False, 0))
        print(f"  \u2717 {filename} — ERROR: {e}")

print(f"\n{sum(1 for _, ok, _ in results if ok)}/{len(STUBS)} components written.")

print("""
Next: Register new components in App.js
──────────────────────────────────────────────────────────────────
Add these imports to App.js (use Python, never PowerShell):

  import CRM            from './components/CRM';
  import Sponsors       from './components/Sponsors';
  import MandAScreen    from './components/MandAScreen';
  import CompsLibrary   from './components/CompsLibrary';
  import PitchTracker   from './components/PitchTracker';
  import ReadingLog     from './components/ReadingLog';
  import CalendarView   from './components/CalendarView';
  import WeeklyDebrief  from './components/WeeklyDebrief';

And add to NAV array + panel switch in App.js.
Use add_nav_entries.py (below) to do this safely.
""")