import { t } from '../../i18n';
import { BRAND_GLYPH, RADAR_BLIPS } from '../../constants';
import styles from './RadarHero.module.css';

interface RadarHeroProps {
  locale: string;
}

export default function RadarHero({ locale }: RadarHeroProps) {
  return (
    <div className={styles.radar} aria-hidden>
      <div className={styles.rings} />
      <div className={styles.sweep} />
      <span className={styles.core}>{BRAND_GLYPH}</span>
      {RADAR_BLIPS.map((blip) => (
        <div
          key={blip.slug}
          className={styles.blip}
          style={{ top: `${blip.top}%`, left: `${blip.left}%`, '--blip-delay': `${blip.delay}s` } as React.CSSProperties}
        >
          <span className={styles.dot} />
          <span className={styles.label}>{t(`category_${blip.slug}`, locale)}</span>
        </div>
      ))}
    </div>
  );
}
