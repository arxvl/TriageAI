/**
 * Stands in for a screen a later phase builds (P04-P09).
 *
 * The routes exist now so the header's role-aware navigation can be built and
 * tested against real paths instead of dead links.
 */
import { strings } from "../../i18n/strings";
import styles from "./Placeholder.module.css";

export function Placeholder({ title }: { title: string }) {
  return (
    <section className={styles.panel}>
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.body}>{strings.placeholder.body}</p>
    </section>
  );
}
