/**
 * W-08's left card: the four status tabs, the kind filter, and the entry table.
 *
 * Two rules the list keeps:
 *
 * - **The counts are the knowledge base's, not the table's.** They come from the
 *   server's `counts` and so do not move when a tab or the kind filter changes,
 *   which is what makes them readable as tabs (FR-39).
 * - **A baseline action set is marked as one.** The five `URGENCY_ACTIONS`
 *   entries are not clinical prose and are never retrieved by similarity, so
 *   each row says which kind it is and the filter can show them alone
 *   (ADR-18, P08 §8.3).
 *
 * The W-08 wireframe also draws an "Updated" column. `kb_entries` carries no
 * timestamp, so the column is left out rather than filled with something that
 * only looks like one.
 */
import type {
  ComplaintOption,
  KBEntryKind,
  KBEntryListResponse,
  KBEntryStatus,
  KBEntrySummary,
} from "../../api/kb";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { complaintName, STATUS_TABS } from "./catalogue";
import styles from "./KnowledgeBase.module.css";

const copy = strings.knowledgeBase;

const KIND_OPTIONS: readonly KBEntryKind[] = ["COMPLAINT", "URGENCY_ACTIONS"];

export function EntryList({
  data,
  isPending,
  isError,
  status,
  kind,
  complaints,
  selectedId,
  canCreate,
  onPickStatus,
  onPickKind,
  onSelect,
  onCreate,
}: {
  data: KBEntryListResponse | undefined;
  isPending: boolean;
  isError: boolean;
  status: KBEntryStatus;
  kind: KBEntryKind | "";
  /** The fixed complaint list, so a row names the complaint rather than its code. */
  complaints: readonly ComplaintOption[];
  selectedId: string | null;
  /** Only an administrator curates content (FR-49, BR-05). */
  canCreate: boolean;
  onPickStatus: (status: KBEntryStatus) => void;
  onPickKind: (kind: KBEntryKind | "") => void;
  onSelect: (entryId: string) => void;
  onCreate: (kind: KBEntryKind) => void;
}) {
  return (
    <div className={styles.listCard}>
      <div className={styles.tabs} role="tablist" aria-label={copy.tabsLabel}>
        {STATUS_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={tab === status}
            className={tab === status ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={() => onPickStatus(tab)}
          >
            {copy.tabLabel
              .replace("{label}", copy.tabs[tab])
              .replace("{count}", String(data?.counts[tab] ?? 0))}
          </button>
        ))}
      </div>

      <div className={styles.listTools}>
        <div className={styles.filterField}>
          <label className={styles.filterLabel} htmlFor="kb-kind">
            {copy.kindFilterLabel}
          </label>
          <select
            id="kb-kind"
            className={styles.select}
            value={kind}
            onChange={(event) => onPickKind(event.target.value as KBEntryKind | "")}
          >
            <option value="">{copy.kindAll}</option>
            {KIND_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {copy.kinds[option]}
              </option>
            ))}
          </select>
        </div>

        {canCreate && (
          <div className={styles.createButtons}>
            <button
              type="button"
              className={styles.createButton}
              onClick={() => onCreate("COMPLAINT")}
            >
              {copy.editor.newEntry}
            </button>
            <button
              type="button"
              className={styles.createButton}
              onClick={() => onCreate("URGENCY_ACTIONS")}
            >
              {copy.editor.newActionSet}
            </button>
          </div>
        )}
      </div>

      <Rows
        items={data?.items}
        isPending={isPending}
        isError={isError}
        hasFilter={kind !== ""}
        complaints={complaints}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  );
}

function Rows({
  items,
  isPending,
  isError,
  hasFilter,
  complaints,
  selectedId,
  onSelect,
}: {
  items: readonly KBEntrySummary[] | undefined;
  isPending: boolean;
  isError: boolean;
  hasFilter: boolean;
  complaints: readonly ComplaintOption[];
  selectedId: string | null;
  onSelect: (entryId: string) => void;
}) {
  if (isError) {
    return (
      <p className={styles.error} role="alert">
        {copy.errors.unexpected}
      </p>
    );
  }

  if (isPending || items === undefined) {
    return <p className={styles.notice}>{copy.loading}</p>;
  }

  if (items.length === 0) {
    return <p className={styles.notice}>{hasFilter ? copy.emptyFiltered : copy.empty}</p>;
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">{copy.columns.entry}</th>
          <th scope="col">{copy.columns.filedUnder}</th>
          <th scope="col">{copy.columns.species}</th>
          <th scope="col">{copy.columns.source}</th>
          <th scope="col">{copy.columns.words}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr
            key={item.id}
            className={item.id === selectedId ? `${styles.row} ${styles.rowSelected}` : styles.row}
          >
            <td data-label={copy.columns.entry}>
              {/* A button, not a row handler: the title is what opens the entry,
                  so a keyboard reaches every row in order (NFR-21, IR-07). */}
              <button
                type="button"
                className={styles.entryButton}
                aria-current={item.id === selectedId}
                onClick={() => onSelect(item.id)}
              >
                {item.title}
              </button>
              <span className={styles.kindTag}>{copy.kinds[item.kind]}</span>
            </td>
            <td data-label={copy.columns.filedUnder}>
              <FiledUnder item={item} complaints={complaints} />
            </td>
            <td data-label={copy.columns.species}>
              {item.species.map((name) => copy.species[name]).join(", ")}
            </td>
            <td data-label={copy.columns.source}>{item.source_title ?? copy.notAvailable}</td>
            <td data-label={copy.columns.words}>
              {(item.kind === "URGENCY_ACTIONS" ? copy.actionCount : copy.wordCount).replace(
                "{count}",
                String(item.word_count),
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * What the entry is filed under: a presenting complaint, or a VTL category.
 *
 * The category goes through `VtlBadge`, which always prints the name and the
 * target waiting time — a category is never shown as colour alone (IR-03).
 */
function FiledUnder({
  item,
  complaints,
}: {
  item: KBEntrySummary;
  complaints: readonly ComplaintOption[];
}) {
  if (item.urgency_category !== null) {
    return <VtlBadge category={item.urgency_category} />;
  }
  return <>{complaintName(item.complaint_code, complaints)}</>;
}
