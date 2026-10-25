/**
 * W-07 Case History (FR-44, FR-45, FR-46, IR-03, IR-04 · UC-11).
 *
 * A searchable archive with the per-case audit timeline beside it. Three things
 * decide its shape:
 *
 * 1. **AI and final are two columns.** The point of the screen is to let a
 *    reviewer see where a person overruled the model, so each row carries both
 *    categories and a text marker when they differ (never colour alone, IR-03).
 *    `is_disagreement` is the server's: the screen does not compare the two.
 * 2. **Search is explicit.** The filter bar edits a draft and the Search button
 *    applies it, as W-07 draws it. Typing a case number does not fire a request
 *    per keystroke, and a half-entered date range is never sent.
 * 3. **Selecting a row reads the audit trail, not the case.** `GET /cases/{id}`
 *    acknowledges the case's red-flag alerts when a reviewer reads it (FR-12), so
 *    browsing the archive must not make that request. The timeline comes from
 *    `GET /cases/{id}/audit`, and an "Open case" link leaves the choice of
 *    opening the case to the reader.
 *
 * Open to all three roles. Nothing here changes a case, so an Administrator's
 * read-only access needs no special handling on this screen (BR-02).
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import {
  HISTORY_PAGE_SIZE,
  listCaseHistory,
  listComplaintOptions,
  readCaseAudit,
  type CaseHistoryFilters,
  type CaseHistoryItem,
  type CaseStatus,
  type Species,
  type VTLCategory,
} from "../../api/cases";
import { AuditTimeline } from "../../components/AuditTimeline";
import { StatusChip } from "../../components/StatusChip";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { formatArrivalTime, formatDisplayDate } from "../../lib/datetime";
import { URGENCY_ORDER } from "../../lib/vtl";
import styles from "./CaseHistory.module.css";

const copy = strings.caseHistory;

const SPECIES_OPTIONS: readonly Species[] = ["DOG", "CAT"];

/** Every status, CLOSED included: this screen is where closed cases are found. */
const STATUS_OPTIONS: readonly CaseStatus[] = [
  "SUBMITTED",
  "PROCESSING",
  "AWAITING_REVIEW",
  "MANUAL_TRIAGE_REQUIRED",
  "CONFIRMED",
  "ADJUSTED",
  "MANUALLY_TRIAGED",
  "CLOSED",
];

/** The filter bar's controls. Empty strings mean "any". */
interface FilterDraft {
  caseNo: string;
  dateFrom: string;
  dateTo: string;
  species: Species | "";
  complaint: string;
  aiCategory: VTLCategory | "";
  finalCategory: VTLCategory | "";
  status: CaseStatus | "";
  disagreement: boolean;
}

const NO_FILTERS: FilterDraft = {
  caseNo: "",
  dateFrom: "",
  dateTo: "",
  species: "",
  complaint: "",
  aiCategory: "",
  finalCategory: "",
  status: "",
  disagreement: false,
};

export function CaseHistory() {
  const [draft, setDraft] = useState<FilterDraft>(NO_FILTERS);
  const [applied, setApplied] = useState<FilterDraft>(NO_FILTERS);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<CaseHistoryItem | null>(null);

  const rangeIsBackwards =
    draft.dateFrom !== "" && draft.dateTo !== "" && draft.dateTo < draft.dateFrom;

  const query = toQuery(applied, page);
  const { data, isPending, isError } = useQuery({
    queryKey: ["cases", "history", query],
    queryFn: () => listCaseHistory(query),
    // Keep the previous page on screen while the next one is in flight.
    placeholderData: (previous) => previous,
  });

  const complaints = useQuery({
    queryKey: ["cases", "complaints"],
    queryFn: listComplaintOptions,
    // A fixed list (FR-10): read once.
    staleTime: Infinity,
  });

  const hasFilters = JSON.stringify(applied) !== JSON.stringify(NO_FILTERS);

  function search(event: FormEvent) {
    event.preventDefault();
    if (rangeIsBackwards) {
      return;
    }
    setApplied(draft);
    setPage(1);
  }

  function clear() {
    setDraft(NO_FILTERS);
    setApplied(NO_FILTERS);
    setPage(1);
  }

  function update<K extends keyof FilterDraft>(key: K, value: FilterDraft[K]) {
    setDraft((previous) => ({ ...previous, [key]: value }));
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>

      <form className={styles.filters} onSubmit={search} aria-label={copy.filtersLabel}>
        <TextField
          id="history-case-no"
          label={copy.caseNoLabel}
          placeholder={copy.caseNoPlaceholder}
          value={draft.caseNo}
          onChange={(value) => update("caseNo", value)}
        />
        <DateField
          id="history-from"
          label={copy.dateFromLabel}
          value={draft.dateFrom}
          onChange={(value) => update("dateFrom", value)}
        />
        <DateField
          id="history-to"
          label={copy.dateToLabel}
          value={draft.dateTo}
          invalid={rangeIsBackwards}
          onChange={(value) => update("dateTo", value)}
        />
        <Select
          id="history-species"
          label={copy.speciesLabel}
          value={draft.species}
          options={SPECIES_OPTIONS.map((value) => ({ value, label: copy.species[value] }))}
          onChange={(value) => update("species", value as Species | "")}
        />
        <Select
          id="history-complaint"
          label={copy.complaintLabel}
          value={draft.complaint}
          options={(complaints.data ?? []).map((option) => ({
            value: option.code,
            label: option.name,
          }))}
          onChange={(value) => update("complaint", value)}
        />
        <Select
          id="history-ai"
          label={copy.aiCategoryLabel}
          value={draft.aiCategory}
          options={URGENCY_ORDER.map((value) => ({ value, label: strings.vtl.codes[value] }))}
          onChange={(value) => update("aiCategory", value as VTLCategory | "")}
        />
        <Select
          id="history-final"
          label={copy.finalCategoryLabel}
          value={draft.finalCategory}
          options={URGENCY_ORDER.map((value) => ({ value, label: strings.vtl.codes[value] }))}
          onChange={(value) => update("finalCategory", value as VTLCategory | "")}
        />
        <Select
          id="history-status"
          label={copy.statusLabel}
          value={draft.status}
          options={STATUS_OPTIONS.map((value) => ({ value, label: copy.status[value] }))}
          onChange={(value) => update("status", value as CaseStatus | "")}
        />

        <label className={styles.check}>
          <input
            type="checkbox"
            checked={draft.disagreement}
            onChange={(event) => update("disagreement", event.target.checked)}
          />
          {copy.disagreementLabel}
        </label>

        <div className={styles.actions}>
          <button type="submit" className={styles.searchButton} disabled={rangeIsBackwards}>
            {copy.search}
          </button>
          <button type="button" className={styles.clearButton} onClick={clear}>
            {copy.clear}
          </button>
        </div>

        {rangeIsBackwards && (
          <p className={styles.fieldError} role="alert">
            {copy.errors.badRange}
          </p>
        )}
      </form>

      <div className={styles.split}>
        <div className={styles.results}>
          <Results
            items={data?.items}
            isPending={isPending}
            isError={isError}
            hasFilters={hasFilters}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />

          {data !== undefined && data.total > 0 && (
            <Pager
              page={data.page}
              limit={data.limit}
              total={data.total}
              shown={data.items.length}
              onPage={setPage}
            />
          )}

          <p className={styles.note}>{copy.caption}</p>
          <p className={styles.note}>{copy.colorNote}</p>
        </div>

        <TimelinePanel selected={selected} />
      </div>
    </div>
  );
}

/** Turn the draft into query parameters, leaving out anything left blank. */
function toQuery(filters: FilterDraft, page: number): CaseHistoryFilters {
  const query: CaseHistoryFilters = { page, limit: HISTORY_PAGE_SIZE };
  const caseNo = filters.caseNo.trim();

  if (caseNo !== "") query.case_no = caseNo;
  if (filters.dateFrom !== "") query.date_from = filters.dateFrom;
  if (filters.dateTo !== "") query.date_to = filters.dateTo;
  if (filters.species !== "") query.species = filters.species;
  if (filters.complaint !== "") query.complaint_code = filters.complaint;
  if (filters.aiCategory !== "") query.ai_category = filters.aiCategory;
  if (filters.finalCategory !== "") query.final_category = filters.finalCategory;
  if (filters.status !== "") query.status = filters.status;
  if (filters.disagreement) query.disagreement = true;

  return query;
}

function Results({
  items,
  isPending,
  isError,
  hasFilters,
  selectedId,
  onSelect,
}: {
  items: readonly CaseHistoryItem[] | undefined;
  isPending: boolean;
  isError: boolean;
  hasFilters: boolean;
  selectedId: string | null;
  onSelect: (item: CaseHistoryItem) => void;
}) {
  // An error is reported even while stale rows are cached: a list that has
  // silently stopped answering is worse than one that says so.
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
    return <p className={styles.notice}>{hasFilters ? copy.emptyFiltered : copy.empty}</p>;
  }

  return (
    <table className={styles.table} aria-label={copy.resultsLabel}>
      <thead>
        <tr>
          <th scope="col">{copy.columns.case}</th>
          <th scope="col">{copy.columns.date}</th>
          <th scope="col">{copy.columns.patient}</th>
          <th scope="col" title={copy.aiColumnHint}>
            {copy.columns.ai}
          </th>
          <th scope="col" title={copy.finalColumnHint}>
            {copy.columns.final}
          </th>
          <th scope="col">{copy.columns.status}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <HistoryRow
            key={item.id}
            item={item}
            isSelected={item.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </tbody>
    </table>
  );
}

function HistoryRow({
  item,
  isSelected,
  onSelect,
}: {
  item: CaseHistoryItem;
  isSelected: boolean;
  onSelect: (item: CaseHistoryItem) => void;
}) {
  return (
    <tr
      className={isSelected ? `${styles.row} ${styles.selected}` : styles.row}
      // A mouse user clicks anywhere on the row; a keyboard user presses the
      // case-number button in the first cell.
      onClick={() => onSelect(item)}
    >
      <td data-label={copy.columns.case}>
        <button
          type="button"
          className={styles.caseButton}
          aria-pressed={isSelected}
          aria-label={copy.selectRow.replace("{caseNo}", item.case_no)}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(item);
          }}
        >
          {item.case_no}
        </button>
      </td>
      <td data-label={copy.columns.date}>{arrivalText(item.created_at)}</td>
      <td data-label={copy.columns.patient}>{patientText(item)}</td>
      <td data-label={copy.columns.ai}>
        <CategoryCell category={item.ai_category} missing={copy.noAiCategory} />
      </td>
      <td data-label={copy.columns.final}>
        <CategoryCell category={item.final_category} missing={copy.notDecided} />
        {item.is_disagreement && (
          <span className={styles.disagreement}>{copy.disagreementMarker}</span>
        )}
      </td>
      <td data-label={copy.columns.status}>
        <StatusChip
          status={item.status}
          recommendedCategory={item.ai_category}
          confirmedCategory={item.final_category}
        />
      </td>
    </tr>
  );
}

function CategoryCell({ category, missing }: { category: VTLCategory | null; missing: string }) {
  if (category === null) {
    return (
      <span className={styles.none}>
        {strings.queue.notAvailable}
        <span className="visuallyHidden">{missing}</span>
      </span>
    );
  }
  return <VtlBadge category={category} />;
}

function Pager({
  page,
  limit,
  total,
  shown,
  onPage,
}: {
  page: number;
  limit: number;
  total: number;
  shown: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  const from = shown === 0 ? 0 : (page - 1) * limit + 1;
  const to = (page - 1) * limit + shown;

  return (
    <nav className={styles.pager} aria-label={copy.paginationLabel}>
      <span>
        {copy.range
          .replace("{from}", String(from))
          .replace("{to}", String(to))
          .replace("{total}", String(total))}
      </span>
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {copy.previous}
      </button>
      <span>{copy.pageOf.replace("{page}", String(page)).replace("{pages}", String(pages))}</span>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {copy.next}
      </button>
    </nav>
  );
}

/**
 * The right-hand panel: the audit timeline of the selected row, with the two
 * FR-46 intervals the component prints. Fetches the audit trail only, never the
 * case itself (see the file comment).
 */
function TimelinePanel({ selected }: { selected: CaseHistoryItem | null }) {
  const caseId = selected?.id ?? "";
  const { data, isPending, isError } = useQuery({
    queryKey: ["cases", "audit", caseId],
    queryFn: () => readCaseAudit(caseId),
    enabled: selected !== null,
  });

  if (selected === null) {
    return (
      <aside className={styles.timeline}>
        <p className={styles.notice}>{copy.selectPrompt}</p>
      </aside>
    );
  }

  return (
    <aside className={styles.timeline}>
      {isPending && <p className={styles.notice}>{strings.caseAudit.loading}</p>}
      {isError && (
        <p className={styles.error} role="alert">
          {strings.caseAudit.errors.unexpected}
        </p>
      )}
      {data !== undefined && <AuditTimeline timeline={data} caseNo={selected.case_no} />}
      <Link className={styles.openCase} to={`/cases/${selected.id}`}>
        {copy.openCase}
      </Link>
    </aside>
  );
}

function arrivalText(iso: string): string {
  const date = formatDisplayDate(iso);
  const time = formatArrivalTime(iso);
  if (date === null || time === null) {
    return strings.queue.notAvailable;
  }
  return copy.arrived.replace("{date}", date).replace("{time}", time);
}

function patientText(item: CaseHistoryItem): string {
  const species = copy.species[item.species];
  return item.pet_name === null
    ? species
    : copy.patient.replace("{species}", species).replace("{name}", item.pet_name);
}

function TextField({
  id,
  label,
  placeholder,
  value,
  onChange,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={styles.input}
        type="search"
        autoComplete="off"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function DateField({
  id,
  label,
  value,
  invalid = false,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  invalid?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className={styles.input}
        type="date"
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function Select({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className={styles.input}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{copy.filterAll}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
