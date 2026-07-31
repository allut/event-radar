import { t } from '../../i18n';
import { cx } from '../../utils';
import { BRAND_GLYPH } from '../../constants';
import styles from './RadarHero.module.css';

// Six taxonomy categories placed as radar blips, positioned (top/left %) around
// the sweep. Presentational layout data scoped to this component — the labels
// themselves come from the shared category_* i18n keys, so they stay localized.
const BLIPS: { slug: string; top: number; left: number; delay: number }[] = [
  { slug: 'music', top: 20, left: 30, delay: 0 },
  { slug: 'theater', top: 32, left: 72, delay: 0.4 },
  { slug: 'exhibitions', top: 58, left: 80, delay: 0.8 },
  { slug: 'nightlife', top: 76, left: 52, delay: 1.2 },
  { slug: 'workshops', top: 66, left: 32, delay: 1.6 },
  { slug: 'family', top: 40, left: 18, delay: 2.0 },
];

interface RadarHeroProps {
  locale: string;
}

export default function RadarHero({ locale }: RadarHeroProps) {
  return (
    <div className={styles.radar} aria-hidden>
      <div className={styles.rings} />
      <div className={styles.sweep} />
      <span className={styles.core}>{BRAND_GLYPH}</span>
      {BLIPS.map((blip) => (
        <div
          key={blip.slug}
          className={styles.blip}
          style={{ top: `${blip.top}%`, left: `${blip.left}%`, '--blip-delay': `${blip.delay}s` } as React.CSSProperties}
        >
          <span className={styles.dot} />
          <span className={cx(styles.label)}>{t(`category_${blip.slug}`, locale)}</span>
        </div>
      ))}
    </div>
  );
}
