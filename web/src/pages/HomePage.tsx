import { Link } from 'react-router-dom';
import { useMemo } from 'react';
import {
  PlayIcon,
  UploadIcon,
  TerminalIcon,
  BookIcon,
  SparkleIcon,
  PlugIcon,
} from '@/components/Icon';
import { useI18n } from '@/i18n/I18nProvider';

/* Floating particle config — generated once to avoid re-renders */
interface Particle {
  left: string;
  size: number;
  delay: string;
  duration: string;
  color: string;
}

function generateParticles(count: number): Particle[] {
  const colors = [
    'oklch(67% 0.21 290 / 0.5)',
    'oklch(72% 0.18 320 / 0.4)',
    'oklch(60% 0.14 240 / 0.45)',
    'oklch(74% 0.16 150 / 0.35)',
    'oklch(68% 0.12 200 / 0.4)',
  ];
  const particles: Particle[] = [];
  for (let i = 0; i < count; i++) {
    particles.push({
      left: `${Math.random() * 100}%`,
      size: 2 + Math.random() * 4,
      delay: `${Math.random() * 8}s`,
      duration: `${6 + Math.random() * 10}s`,
      color: colors[i % colors.length],
    });
  }
  return particles;
}

/* Card accent colors for the 4 entry cards */
const CARD_ACCENTS = [
  { gradient: 'linear-gradient(135deg, oklch(67% 0.21 290), oklch(56% 0.20 320))', glow: 'oklch(67% 0.21 290 / 0.3)' },
  { gradient: 'linear-gradient(135deg, oklch(72% 0.14 240), oklch(60% 0.16 210))', glow: 'oklch(72% 0.14 240 / 0.25)' },
  { gradient: 'linear-gradient(135deg, oklch(68% 0.16 150), oklch(58% 0.14 180))', glow: 'oklch(68% 0.16 150 / 0.25)' },
  { gradient: 'linear-gradient(135deg, oklch(74% 0.14 60), oklch(62% 0.12 40))', glow: 'oklch(74% 0.14 60 / 0.25)' },
];

export function HomePage() {
  const { t } = useI18n();
  const particles = useMemo(() => generateParticles(18), []);

  const entries = [
    {
      to: '/tasks',
      title: t('home.entries.tasks.title'),
      desc: t('home.entries.tasks.desc'),
      icon: PlayIcon,
      accent: 0,
    },
    {
      to: '/upload',
      title: t('home.entries.upload.title'),
      desc: t('home.entries.upload.desc'),
      icon: UploadIcon,
      accent: 1,
    },
    {
      to: '/runs',
      title: t('home.entries.runs.title'),
      desc: t('home.entries.runs.desc'),
      icon: TerminalIcon,
      accent: 2,
    },
    {
      to: '/docs/architecture',
      title: t('home.entries.docs.title'),
      desc: t('home.entries.docs.desc'),
      icon: BookIcon,
      accent: 3,
    },
  ];

  return (
    <div className="relative min-h-[calc(100vh-56px)] overflow-hidden">
      {/* Animated gradient background */}
      <div className="hero-gradient-bg" />
      <div className="hero-grid-overlay" />

      {/* Floating orbs (large ambient blobs) */}
      <div
        className="absolute pointer-events-none"
        style={{
          width: 320, height: 320, top: '5%', left: '8%',
          borderRadius: '50%',
          background: 'radial-gradient(circle, oklch(67% 0.21 290 / 0.08), transparent 70%)',
          filter: 'blur(60px)',
          animation: 'orb-float 18s ease-in-out infinite',
        }}
      />
      <div
        className="absolute pointer-events-none"
        style={{
          width: 260, height: 260, top: '40%', right: '5%',
          borderRadius: '50%',
          background: 'radial-gradient(circle, oklch(60% 0.16 220 / 0.10), transparent 70%)',
          filter: 'blur(50px)',
          animation: 'orb-float 14s ease-in-out infinite reverse',
        }}
      />

      {/* Floating particles */}
      {particles.map((particle, index) => (
        <div
          key={index}
          className="float-particle"
          style={{
            left: particle.left,
            bottom: '-10px',
            width: particle.size,
            height: particle.size,
            background: particle.color,
            animationDelay: particle.delay,
            animationDuration: particle.duration,
          }}
        />
      ))}

      {/* Main content */}
      <div className="relative z-10 max-w-6xl mx-auto px-6 py-16 md:py-24">
        {/* Tag chips — fade in */}
        <div
          className="flex items-center gap-2 mb-6"
          style={{ animation: 'hero-fade-in 0.6s var(--ease-out-expo) both' }}
        >
          <span
            className="chip"
            style={{
              borderColor: 'oklch(67% 0.21 290 / 0.4)',
              background: 'oklch(67% 0.21 290 / 0.1)',
            }}
          >
            <SparkleIcon size={12} /> {t('home.tag.console')}
          </span>
          <span className="chip" style={{ color: 'var(--color-fg-faint)' }}>
            v0.1 · console
          </span>
        </div>

        {/* Hero title — animated gradient text */}
        <h1
          className="text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.05] max-w-4xl"
          style={{ animation: 'hero-fade-in 0.8s var(--ease-out-expo) 0.1s both' }}
        >
          {t('home.title.before')}{' '}
          <span
            style={{
              backgroundImage:
                'linear-gradient(90deg, oklch(72% 0.22 290), oklch(68% 0.20 340), oklch(74% 0.18 240), oklch(72% 0.22 290))',
              backgroundSize: '300% 100%',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              animation: 'gradient-text-shift 6s ease-in-out infinite',
            }}
          >
            Data-Agent
          </span>{' '}
          {t('home.title.after')}
        </h1>

        <p
          className="mt-5 text-[color:var(--color-fg-muted)] max-w-2xl text-lg md:text-xl leading-relaxed"
          style={{ animation: 'hero-fade-in 0.8s var(--ease-out-expo) 0.2s both' }}
        >
          {t('home.subtitle')}
        </p>

        {/* CTA buttons — shimmer + glow */}
        <div
          className="mt-10 flex flex-wrap gap-3"
          style={{ animation: 'hero-fade-in 0.8s var(--ease-out-expo) 0.35s both' }}
        >
          <Link
            to="/tasks"
            className="btn btn-primary btn-lg btn-shimmer"
            style={{ animation: 'breathe-glow 3s ease-in-out infinite' }}
          >
            <PlayIcon /> {t('home.cta.start')}
          </Link>
          <Link to="/upload" className="btn btn-lg btn-shimmer">
            <UploadIcon /> {t('home.cta.upload')}
          </Link>
          <Link to="/settings" className="btn btn-ghost btn-lg" style={{ transition: 'all 0.3s var(--ease-out-expo)' }}>
            <PlugIcon /> {t('home.cta.configure')}
          </Link>
        </div>

        {/* Feature cards — stagger scale-in with hover glow */}
        <div className="mt-16 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
          {entries.map((entry, index) => {
            const cardAccent = CARD_ACCENTS[entry.accent];
            return (
              <Link
                key={entry.to}
                to={entry.to}
                className="card-glow surface p-5 group transition-all duration-300 hover:-translate-y-1.5"
                style={{
                  animation: `hero-scale-in 0.6s var(--ease-out-expo) ${0.4 + index * 0.1}s both`,
                  transitionTimingFunction: 'var(--ease-out-expo)',
                }}
                onMouseEnter={(event) => {
                  const target = event.currentTarget as HTMLElement;
                  target.style.boxShadow = `0 8px 32px -8px ${cardAccent.glow}, 0 0 0 1px ${cardAccent.glow}`;
                  target.style.borderColor = 'transparent';
                }}
                onMouseLeave={(event) => {
                  const target = event.currentTarget as HTMLElement;
                  target.style.boxShadow = '';
                  target.style.borderColor = '';
                }}
              >
                <div
                  className="w-10 h-10 grid place-items-center rounded-lg mb-4 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3"
                  style={{
                    background: cardAccent.gradient,
                    color: 'var(--color-accent-fg)',
                    boxShadow: `0 4px 14px -4px ${cardAccent.glow}`,
                  }}
                >
                  <entry.icon size={20} />
                </div>
                <div className="font-semibold mb-1.5 tracking-tight text-base">{entry.title}</div>
                <div className="text-sm text-[color:var(--color-fg-muted)] leading-relaxed">
                  {entry.desc}
                </div>
              </Link>
            );
          })}
        </div>

        {/* ── Architecture overview ── */}
        <section
          className="mt-20"
          style={{ animation: 'hero-fade-in 0.8s var(--ease-out-expo) 0.85s both' }}
        >
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-2">
            {t('home.arch.title')}
          </h2>
          <p className="text-[color:var(--color-fg-muted)] max-w-3xl mb-8 leading-relaxed">
            {t('home.arch.subtitle')}
          </p>

          {/* Stat pills */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
            {([
              { value: 9, label: t('home.arch.stat.nodes'), color: 'var(--color-accent)' },
              { value: 7, label: t('home.arch.stat.routers'), color: 'var(--color-info)' },
              { value: 4, label: t('home.arch.stat.budgets'), color: 'var(--color-success)' },
              { value: 3, label: t('home.arch.stat.roles'), color: 'var(--color-warning)' },
            ] as const).map((stat) => (
              <div
                key={stat.label}
                className="surface p-4 text-center transition-transform duration-300 hover:-translate-y-0.5"
              >
                <div className="text-3xl font-bold" style={{ color: stat.color }}>
                  {stat.value}
                </div>
                <div className="text-xs text-[color:var(--color-fg-muted)] mt-1 uppercase tracking-wider">
                  {stat.label}
                </div>
              </div>
            ))}
          </div>

          {/* Pipeline cards */}
          <h3 className="text-lg font-semibold mb-4">{t('home.arch.pipeline.title')}</h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-10">
            {([
              { title: t('home.arch.pipeline.plan'), desc: t('home.arch.pipeline.plan.desc'), emoji: '📋', accent: CARD_ACCENTS[0] },
              { title: t('home.arch.pipeline.schedule'), desc: t('home.arch.pipeline.schedule.desc'), emoji: '🔀', accent: CARD_ACCENTS[1] },
              { title: t('home.arch.pipeline.execute'), desc: t('home.arch.pipeline.execute.desc'), emoji: '⚙️', accent: CARD_ACCENTS[2] },
              { title: t('home.arch.pipeline.reflect'), desc: t('home.arch.pipeline.reflect.desc'), emoji: '🔍', accent: CARD_ACCENTS[3] },
            ] as const).map((step, index) => (
              <div
                key={step.title}
                className="surface p-5 relative transition-all duration-300 hover:-translate-y-1"
              >
                {index < 3 && (
                  <span className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 text-[color:var(--color-fg-faint)] text-lg z-10">→</span>
                )}
                <div className="text-2xl mb-2">{step.emoji}</div>
                <div className="font-semibold mb-1">{step.title}</div>
                <div className="text-sm text-[color:var(--color-fg-muted)] leading-relaxed">{step.desc}</div>
              </div>
            ))}
          </div>

          {/* Workflow SVG */}
          <div className="surface p-6 relative overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">{t('home.arch.workflow.title')}</h3>
                <p className="text-sm text-[color:var(--color-fg-muted)]">{t('home.arch.workflow.desc')}</p>
              </div>
              <Link
                to="/docs/architecture"
                className="btn btn-sm"
              >
                <BookIcon size={14} /> {t('home.arch.readMore')}
              </Link>
            </div>
            <div className="rounded-lg overflow-hidden border border-[color:var(--color-border)] bg-white p-4">
              <img
                src="/static/docs/agent-workflow.svg"
                alt="Agent workflow DAG"
                className="w-full h-auto"
                loading="lazy"
              />
            </div>
          </div>
        </section>

        {/* ── §1 Overview: ReAct Gap → Solution ── */}
        <section className="mt-20">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-2">{t('home.arch.overview.title')}</h2>
          <p className="text-[color:var(--color-fg-muted)] max-w-3xl mb-8 leading-relaxed">{t('home.arch.overview.subtitle')}</p>

          {/* Gap card */}
          <div className="surface p-6 mb-6" style={{ borderLeft: '4px solid var(--color-status-failed)' }}>
            <div className="flex items-center gap-2 mb-1 font-semibold" style={{ color: 'var(--color-status-failed)' }}>⚠️ {t('home.arch.overview.gap.title')}</div>
            <p className="text-xs text-[color:var(--color-fg-muted)] mb-4">{t('home.arch.overview.gap.subtitle')}</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {[
                { emoji: '🌫', text: t('home.arch.overview.gap.context') },
                { emoji: '🪤', text: t('home.arch.overview.gap.wander') },
                { emoji: '💀', text: t('home.arch.overview.gap.deadloop') },
              ].map((item) => (
                <div key={item.emoji} className="surface p-3 text-sm leading-relaxed">
                  <span className="mr-1">{item.emoji}</span>{item.text}
                </div>
              ))}
            </div>
          </div>

          {/* Solution card */}
          <div className="surface p-6" style={{ borderLeft: '4px solid var(--color-status-done)' }}>
            <div className="flex items-center gap-2 mb-1 font-semibold" style={{ color: 'var(--color-status-done)' }}>🎯 {t('home.arch.overview.solution.title')}</div>
            <p className="text-xs text-[color:var(--color-fg-muted)] mb-4">{t('home.arch.overview.solution.subtitle')}</p>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              {([
                { emoji: '🧭', title: t('home.arch.overview.solution.plan'), desc: t('home.arch.overview.solution.planDesc') },
                { emoji: '⚙️', title: t('home.arch.overview.solution.exec'), desc: t('home.arch.overview.solution.execDesc') },
                { emoji: '🔍', title: t('home.arch.overview.solution.review'), desc: t('home.arch.overview.solution.reviewDesc') },
                { emoji: '🛡', title: t('home.arch.overview.solution.scaffold'), desc: t('home.arch.overview.solution.scaffoldDesc') },
              ] as const).map((item) => (
                <div key={item.emoji} className="surface p-4 transition-all duration-300 hover:-translate-y-0.5">
                  <div className="text-2xl mb-2">{item.emoji}</div>
                  <div className="font-semibold mb-1 text-sm">{item.title}</div>
                  <div className="text-xs text-[color:var(--color-fg-muted)] leading-relaxed">{item.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── §2 Topology: 9 nodes, 4 layers ── */}
        <section className="mt-16">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-2">{t('home.arch.topology.title')}</h2>
          <p className="text-[color:var(--color-fg-muted)] max-w-3xl mb-8 leading-relaxed">{t('home.arch.topology.subtitle')}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {([
              { emoji: '📋', title: t('home.arch.topology.scheduler'), desc: t('home.arch.topology.schedulerDesc'), accent: CARD_ACCENTS[1] },
              { emoji: '⚙️', title: t('home.arch.topology.executor'), desc: t('home.arch.topology.executorDesc'), accent: CARD_ACCENTS[2] },
              { emoji: '🔍', title: t('home.arch.topology.reflector'), desc: t('home.arch.topology.reflectorDesc'), accent: CARD_ACCENTS[3] },
              { emoji: '❌', title: t('home.arch.topology.nodeFailure'), desc: t('home.arch.topology.nodeFailureDesc'), accent: CARD_ACCENTS[0] },
              { emoji: '👋', title: t('home.arch.topology.nudge'), desc: t('home.arch.topology.nudgeDesc'), accent: CARD_ACCENTS[1] },
              { emoji: '✅', title: t('home.arch.topology.finalize'), desc: t('home.arch.topology.finalizeDesc'), accent: CARD_ACCENTS[2] },
            ] as const).map((node) => (
              <div
                key={node.emoji}
                className="surface p-5 transition-all duration-300 hover:-translate-y-1"
                style={{ borderTop: `3px solid ${node.accent.glow.replace('/ 0.', '/ 0.8')}` }}
              >
                <div className="text-2xl mb-2">{node.emoji}</div>
                <div className="font-semibold mb-1 text-sm">{node.title}</div>
                <div className="text-xs text-[color:var(--color-fg-muted)] leading-relaxed">{node.desc}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── §3 Budget: 4 concentric layers ── */}
        <section className="mt-16">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-2">{t('home.arch.budget.title')}</h2>
          <p className="text-[color:var(--color-fg-muted)] max-w-3xl mb-8 leading-relaxed">{t('home.arch.budget.subtitle')}</p>
          <div className="space-y-3">
            {([
              { title: t('home.arch.budget.l1.title'), desc: t('home.arch.budget.l1.desc'), color: 'var(--color-status-failed)' },
              { title: t('home.arch.budget.l2.title'), desc: t('home.arch.budget.l2.desc'), color: 'var(--color-warning)' },
              { title: t('home.arch.budget.l3.title'), desc: t('home.arch.budget.l3.desc'), color: 'var(--color-info)' },
              { title: t('home.arch.budget.l4.title'), desc: t('home.arch.budget.l4.desc'), color: 'var(--color-accent)' },
            ] as const).map((layer) => (
              <div
                key={layer.title}
                className="surface p-5 transition-all duration-300 hover:-translate-y-0.5"
                style={{ borderLeft: `4px solid ${layer.color}` }}
              >
                <div className="font-semibold mb-1 text-sm">{layer.title}</div>
                <div className="text-xs text-[color:var(--color-fg-muted)] leading-relaxed">{layer.desc}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── §4 Anti-hallucination: data profile ── */}
        <section className="mt-16">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-2">{t('home.arch.antiHallucination.title')}</h2>
          <p className="text-[color:var(--color-fg-muted)] max-w-3xl mb-8 leading-relaxed">{t('home.arch.antiHallucination.subtitle')}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="surface p-6" style={{ borderLeft: '4px solid var(--color-status-failed)' }}>
              <div className="font-semibold mb-2 text-sm flex items-center gap-2" style={{ color: 'var(--color-status-failed)' }}>
                ❌ {t('home.arch.antiHallucination.without')}
              </div>
              <p className="text-xs text-[color:var(--color-fg-muted)] leading-relaxed">{t('home.arch.antiHallucination.withoutDesc')}</p>
            </div>
            <div className="surface p-6" style={{ borderLeft: '4px solid var(--color-status-done)' }}>
              <div className="font-semibold mb-2 text-sm flex items-center gap-2" style={{ color: 'var(--color-status-done)' }}>
                ✅ {t('home.arch.antiHallucination.with')}
              </div>
              <p className="text-xs text-[color:var(--color-fg-muted)] leading-relaxed">{t('home.arch.antiHallucination.withDesc')}</p>
            </div>
          </div>
        </section>

        {/* Connector status — elegant glass card */}
        <div
          className="mt-16 surface p-6 relative overflow-hidden"
          style={{
            animation: 'hero-fade-in 0.8s var(--ease-out-expo) 0.9s both',
            background: 'color-mix(in oklch, var(--color-surface) 90%, var(--color-accent) 10%)',
            backdropFilter: 'blur(16px)',
          }}
        >
          {/* Subtle accent border-top */}
          <div
            className="absolute top-0 left-0 right-0 h-[2px]"
            style={{
              background: 'linear-gradient(90deg, transparent, oklch(67% 0.21 290 / 0.6), oklch(60% 0.16 240 / 0.4), transparent)',
            }}
          />
          <div className="flex items-start gap-4">
            <div
              className="w-10 h-10 grid place-items-center rounded-lg shrink-0"
              style={{
                background: 'linear-gradient(135deg, oklch(67% 0.21 290 / 0.2), oklch(60% 0.16 240 / 0.15))',
                color: 'var(--color-accent)',
                border: '1px solid oklch(67% 0.21 290 / 0.2)',
              }}
            >
              <PlugIcon size={18} />
            </div>
            <div className="flex-1">
              <div className="font-semibold mb-1">{t('home.connector.title')}</div>
              <div className="text-sm text-[color:var(--color-fg-muted)] leading-relaxed">
                {t('home.connector.desc.before')}
                <Link
                  to="/settings"
                  className="text-[color:var(--color-accent)] underline underline-offset-2 transition-colors hover:text-[color:var(--color-accent-hover)]"
                >
                  {t('home.connector.link')}
                </Link>
                {t('home.connector.desc.after')}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
