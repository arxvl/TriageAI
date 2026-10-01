/**
 * W-02 Triage Queue, and W-11, which is the same screen below 900 px (FR-29,
 * FR-30, FR-36, FR-39, IR-03, IR-22 · UC-04).
 *
 * The queue is the screen the clinic works from, so four things matter more than
 * the layout:
 *
 * 1. **The order is the server's.** FR-29 ranks RED first, then cases with no
 *    category at all — an unclassified case might be the most urgent one in the
 *    room — then ORANGE down to BLUE, oldest first within a rank. The rows are
 *    rendered in the order they arrive and never re-sorted here, so one
 *    definition of urgency exists rather than two.
 * 2. **Waiting time is read, not computed.** `waiting_minutes`, `target_minutes`
 *    and `is_overdue` all come from the response, measured against one clock for
 *    every row (FR-30). The only judgement this screen makes is `isOverdueForDisplay`.
 * 3. **No category is shown as settled.** Every row carries a `StatusChip`, so an
 *    AI recommendation reads as pending until a reviewer decides (FR-36, IR-04).
 * 4. **Polling pauses on a hidden tab** (IR-22). TanStack Query's focus manager
 *    listens to `visibilitychange`, and `refetchIntervalInBackground: false` —
 *    the default, set here because the requirement depends on it — is what makes
 *    a backgrounded tab stop asking.
 *
 * The counters describe the whole open queue, not the filtered rows, which is why
 * clicking one can apply a filter without the numbers moving underneath.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  listCases,
  QUEUE_POLL_INTERVAL_MS,
  type CaseQueueCounts,
  type CaseQueueFilters,
  type CaseQueueItem,
  type CaseStatus,
  type QueueCategoryFilter,
  type Species,
} from "../../api/cases";
import { RedFlagBanner } from "../../components/RedFlagBanner";
import { StatusChip } from "../../components/StatusChip";
import { VtlBadge } from "../../components/VtlBadge";
import { strings } from "../../i18n/strings";
import { clinicDaysAgo, clinicToday, formatArrivalTime } from "../../lib/datetime";
import {
  badgeCategoryOf,
  isOverdueForDisplay,
  URGENCY_ORDER,
  waitProgressPercent,
} from "../../lib/vtl";
import styles from "./TriageQueue.module.css";

const copy = strings.queue;

/** Long enough that typing a case number is one request, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 300;

/** How often the "Updated N s ago" indicator re-renders. */
const CLOCK_TICK_MS = 1_000;

/**
 * The date filter (FR-39).
 *
 * It defaults to ALL, not TODAY as W-02 draws it: the queue already lists only
 * open cases, so defaulting to today would hide a case left open overnight —
 * exactly the case most in need of being seen.
 */
type DateRange = "ALL" | "TODAY" | "LAST_7_DAYS";

const SPECIES_OPTIONS: readonly Species[] = ["DOG", "CAT"];

const CATEGORY_OPTIONS: readonly QueueCategoryFilter[] = [...URGENCY_ORDER, "MANUAL"];

/** CLOSED is absent: the queue lists open cases, so it would always be empty. */
const STATUS_OPTIONS: readonly Exclude<CaseStatus, "CLOSED">[] = [
  "SUBMITTED",
  "PROCESSING",
  "AWAITING_REVIEW",
  "MANUAL_TRIAGE_REQUIRED",
  "CONFIRMED",
  "ADJUSTED",
  "MANUALLY_TRIAGED",
];

const DATE_RANGE_OPTIONS: readonly DateRange[] = ["ALL", "TODAY", "LAST_7_DAYS"];

interface FilterState {
  species: Species | "";
  category: QueueCategoryFilter | "";
  status: Exclude<CaseStatus, "CLOSED"> | "";
  dateRange: DateRange;
}

const NO_FILTERS: FilterState = { species: "", category: "", status: "", dateRange: "ALL" };

export function TriageQueue() {
  const navigate = useNavigate();

  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search, SEARCH_DEBOUNCE_MS);

  const query = useMemo(() => toQueryFilters(filters, debouncedSearch), [filters, debouncedSearch]);

  const { data, isPending, isError, dataUpdatedAt } = useQuery({
    queryKey: ["cases", "queue", query],
    queryFn: () => listCases(query),
    refetchInterval: QUEUE_POLL_INTERVAL_MS,
    // IR-22: a backgrounded tab must stop polling. This is the default; it is
    // written out because the requirement rests on it.
    refetchIntervalInBackground: false,
    // Keep the previous rows on screen while a filter change is in flight, so the
    // table does not blink empty between two valid states.
    placeholderData: (previous) => previous,
  });

  const hasFilters = Object.keys(query).length > 0;

  function clearFilters() {
    setFilters(NO_FILTERS);
    setSearch("");
  }

  function setCategory(category: QueueCategoryFilter | "") {
    setFilters((previous) => ({ ...previous, category }));
  }

  return (
    <div className={styles.page}>
      {/* Empty until P05 runs the red-flag pre-screen (FR-12, NFR-05). */}
      <RedFlagBanner alerts={[]} />

      <div className={styles.header}>
        <h1 className={styles.title}>{copy.title}</h1>
        <div className={styles.headerRight}>
          <UpdatedAgo updatedAt={dataUpdatedAt} />
          <button
            type="button"
            className={styles.newCase}
            onClick={() => void navigate("/cases/new")}
          >
            {copy.newCase}
          </button>
        </div>
      </div>

      <Counters
        counts={data?.counts}
        activeCategory={filters.category}
        onPickCategory={setCategory}
      />

      <Filters filters={filters} search={search} onSearch={setSearch} onChange={setFilters} />

      <Rows
        items={data?.items}
        isPending={isPending}
        isError={isError}
        hasFilters={hasFilters}
        onClearFilters={clearFilters}
      />

      {/* The standing reminder behind IR-03, kept on the screen it describes. */}
      <p className={styles.colorNote}>{copy.colorNote}</p>
    </div>
  );
}

/**
 * The table, or the one sentence that stands in for it.
 *
 * The order of these states matters: an error is reported even while stale rows
 * are still in the cache, because a queue that has silently stopped updating is
 * worse than one that says so.
 */
function Rows({
  items,
  isPending,
  isError,
  hasFilters,
  onClearFilters,
}: {
  items: readonly CaseQueueItem[] | undefined;
  isPending: boolean;
  isError: boolean;
  hasFilters: boolean;
  onClearFilters: () => void;
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
    return (
      <div className={styles.notice}>
        <p className={styles.noticeText}>{hasFilters ? copy.emptyFiltered : copy.empty}</p>
        {hasFilters && (
          <button type="button" className={styles.clearFilters} onClick={onClearFilters}>
            {copy.clearFilters}
          </button>
        )}
      </div>
    );
  }

  return <QueueTable items={items} />;
}

/**
 * Turn the filter controls into query parameters.
 *
 * A date range becomes two inclusive calendar dates in the clinic's timezone,
 * which is what the server reads them as.
 */
function toQueryFilters(filters: FilterState, search: string): CaseQueueFilters {
  const trimmed = search.trim();
  const query: CaseQueueFilters = {};

  if (filters.species !== "") {
    query.species = filters.species;
  }
  if (filters.category !== "") {
    query.category = filters.category;
  }
  if (filters.status !== "") {
    query.status = filters.status;
  }
  if (filters.dateRange === "TODAY") {
    query.date_from = clinicToday();
  } else if (filters.dateRange === "LAST_7_DAYS") {
    query.date_from = clinicDaysAgo(6);
  }
  if (trimmed !== "") {
    query.q = trimmed;
  }

  return query;
}

/** Hold a value back until it has stopped changing, so typing is one request. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}

/**
 * "Updated 5 s ago · auto-refresh every 15 s" (IR-22).
 *
 * It ticks once a second so the number is honest about how stale the rows are.
 * Not a live region: a screen reader announcing the second count would make the
 * queue unusable.
 */
function UpdatedAgo({ updatedAt }: { updatedAt: number }) {
  // The clock is read in the interval, never during render: a component that
  // asked the time while rendering would give a different answer on every
  // re-render. Until the first tick `now` is 0, which clamps to "just now" —
  // true, since the rows have only arrived.
  const [now, setNow] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  if (updatedAt === 0) {
    return null;
  }

  const seconds = Math.max(0, Math.floor((now - updatedAt) / 1000));
  return (
    <span className={styles.updated} aria-live="off">
      {seconds === 0 ? copy.updatedJustNow : copy.updatedAgo.replace("{seconds}", String(seconds))}
    </span>
  );
}

/**
 * The counter tiles above the table.
 *
 * Each category tile is a button that applies its own filter, and pressing the
 * active one clears it. The numbers always describe the whole open queue, so they
 * do not move when a filter is on — which is what makes them usable as filters.
 */
function Counters({
  counts,
  activeCategory,
  onPickCategory,
}: {
  counts: CaseQueueCounts | undefined;
  activeCategory: QueueCategoryFilter | "";
  onPickCategory: (category: QueueCategoryFilter | "") => void;
}) {
  if (counts === undefined) {
    return null;
  }

  return (
    <div className={styles.counters} role="group" aria-label={copy.countersLabel}>
      {CATEGORY_OPTIONS.map((category) => {
        const isActive = activeCategory === category;
        const name = strings.vtl.codes[category];
        return (
          <button
            key={category}
            type="button"
            className={isActive ? `${styles.counter} ${styles.counterActive}` : styles.counter}
            aria-pressed={isActive}
            title={(isActive ? copy.counterFilterClearHint : copy.counterFilterHint).replace(
              "{category}",
              name,
            )}
            onClick={() => onPickCategory(isActive ? "" : category)}
          >
            <VtlBadge category={category} />
            <b className={styles.counterValue}>
              {category === "MANUAL" ? counts.manual_count : counts.by_category[category]}
            </b>
            {category === "MANUAL" && (
              <span className={styles.counterCaption}>{strings.vtl.manualCaption}</span>
            )}
          </button>
        );
      })}

      {/* Not a filter: "awaiting review" spans several categories (FR-36). */}
      <p className={styles.awaiting}>
        <b className={styles.counterValue}>{counts.awaiting_review_count}</b>
        <span className={styles.counterCaption}>{copy.awaitingReviewCaption}</span>
      </p>
    </div>
  );
}

function Filters({
  filters,
  search,
  onSearch,
  onChange,
}: {
  filters: FilterState;
  search: string;
  onSearch: (value: string) => void;
  onChange: (update: (previous: FilterState) => FilterState) => void;
}) {
  return (
    <div className={styles.filters}>
      <div className={styles.searchField}>
        <label className="visuallyHidden" htmlFor="queue-search">
          {copy.searchLabel}
        </label>
        <input
          id="queue-search"
          className={styles.search}
          type="search"
          autoComplete="off"
          placeholder={copy.searchPlaceholder}
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
      </div>

      <Select
        id="queue-species"
        label={copy.speciesFilterLabel}
        value={filters.species}
        allLabel={copy.filterAll}
        options={SPECIES_OPTIONS.map((value) => ({ value, label: copy.species[value] }))}
        onChange={(value) =>
          onChange((previous) => ({ ...previous, species: value as Species | "" }))
        }
      />

      <Select
        id="queue-category"
        label={copy.categoryFilterLabel}
        value={filters.category}
        allLabel={copy.filterAll}
        options={CATEGORY_OPTIONS.map((value) => ({ value, label: strings.vtl.codes[value] }))}
        onChange={(value) =>
          onChange((previous) => ({ ...previous, category: value as QueueCategoryFilter | "" }))
        }
      />

      <Select
        id="queue-status"
        label={copy.statusFilterLabel}
        value={filters.status}
        allLabel={copy.statusAll}
        options={STATUS_OPTIONS.map((value) => ({ value, label: copy.status[value] }))}
        onChange={(value) =>
          onChange((previous) => ({
            ...previous,
            status: value as Exclude<CaseStatus, "CLOSED"> | "",
          }))
        }
      />

      {/* No "all" entry: ALL is already one of the three ranges. */}
      <Select
        id="queue-date"
        label={copy.dateFilterLabel}
        value={filters.dateRange}
        options={DATE_RANGE_OPTIONS.map((value) => ({ value, label: copy.dateRanges[value] }))}
        onChange={(value) =>
          onChange((previous) => ({ ...previous, dateRange: value as DateRange }))
        }
      />
    </div>
  );
}

function Select({
  id,
  label,
  value,
  allLabel,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  /** When given, an extra first entry whose value is "" — "no filter". */
  allLabel?: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className={styles.filterField}>
      <label className={styles.filterLabel} htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className={styles.select}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {allLabel !== undefined && <option value="">{allLabel}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * The W-02 table, which below 900 px becomes one card per case (W-11).
 *
 * That transformation is pure CSS, and it works because every cell carries
 * `data-label`: the card layout prints the attribute as the field's name, so a
 * value never ends up on screen without the column heading it belonged to.
 */
function QueueTable({ items }: { items: readonly CaseQueueItem[] }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">{copy.columns.urgency}</th>
          <th scope="col">{copy.columns.case}</th>
          <th scope="col">{copy.columns.patient}</th>
          <th scope="col">{copy.columns.complaint}</th>
          <th scope="col">{copy.columns.arrived}</th>
          <th scope="col">{copy.columns.waiting}</th>
          <th scope="col">{copy.columns.status}</th>
          <th scope="col">{copy.columns.flags}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <QueueRow key={item.id} item={item} />
        ))}
      </tbody>
    </table>
  );
}

function QueueRow({ item }: { item: CaseQueueItem }) {
  const navigate = useNavigate();
  const overdue = isOverdueForDisplay(item.category, item.is_overdue);

  function open() {
    void navigate(`/cases/${item.id}`);
  }

  return (
    <tr
      className={overdue ? `${styles.row} ${styles.overdue}` : styles.row}
      // A mouse user clicks anywhere on the row; a keyboard user follows the
      // case-number link in the next cell, which is a real link rather than a
      // handler bolted onto a <tr> (NFR-21, IR-07).
      onClick={open}
    >
      <td data-label={copy.columns.urgency}>
        <VtlBadge category={badgeCategoryOf(item)} />
      </td>
      <td data-label={copy.columns.case}>
        <a
          className={styles.caseLink}
          href={`/cases/${item.id}`}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            open();
          }}
        >
          {item.case_no}
        </a>
      </td>
      <td data-label={copy.columns.patient}>{patientText(item)}</td>
      <td data-label={copy.columns.complaint}>
        {item.primary_complaint_name ?? copy.notAvailable}
      </td>
      <td data-label={copy.columns.arrived}>
        {formatArrivalTime(item.created_at) ?? copy.notAvailable}
      </td>
      <td data-label={copy.columns.waiting}>
        <WaitingCell item={item} overdue={overdue} />
      </td>
      <td data-label={copy.columns.status}>
        <StatusChip
          status={item.status}
          recommendedCategory={item.recommended_category}
          confirmedCategory={item.confirmed_category}
        />
      </td>
      <td data-label={copy.columns.flags}>
        {item.has_red_flag && (
          <span className={styles.flag}>
            <span aria-hidden="true">!</span>
            <span className="visuallyHidden">{copy.redFlag}</span>
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * "6 / 15 min", or "64 / 60 min · overdue" once the target has passed (FR-29, FR-30).
 *
 * The elapsed time is always shown, including for RED, whose target is 0 and
 * which therefore reads "1 / 0 min": how long an emergency has been waiting is
 * exactly what a reviewer scanning this column needs. What RED does not get is
 * the word "overdue", which would be on every RED row and so say nothing.
 *
 * The bar is decoration — the text beside it is the value, so the cell reads the
 * same with styles off. A case with no category has no target and so no bar.
 */
function WaitingCell({ item, overdue }: { item: CaseQueueItem; overdue: boolean }) {
  const hasTarget = item.target_minutes !== null;
  const percent = waitProgressPercent(item.waiting_minutes, item.target_minutes);
  // A target of 0 is passed the moment the case arrives, so the bar is full and
  // red from the start even though the row is not called overdue.
  const atTargetZero = item.target_minutes === 0;
  const text = hasTarget
    ? copy.waiting
        .replace("{waiting}", String(item.waiting_minutes))
        .replace("{target}", String(item.target_minutes))
    : copy.waitingNoTarget.replace("{waiting}", String(item.waiting_minutes));

  return (
    <span className={styles.waiting}>
      {hasTarget && (
        <span
          className={overdue || atTargetZero ? `${styles.bar} ${styles.barOver}` : styles.bar}
          aria-hidden="true"
        >
          <i className={styles.barFill} style={{ width: `${percent}%` }} />
        </span>
      )}
      {overdue ? (
        <b className={styles.overdueText}>
          {text} · {copy.overdueSuffix}
        </b>
      ) : (
        text
      )}
    </span>
  );
}

/** "Dog · Bantay · 8 y", with whatever parts the case actually has. */
function patientText(item: CaseQueueItem): string {
  const parts: string[] = [copy.species[item.species]];

  if (item.pet_name !== null) {
    parts.push(item.pet_name);
  }
  if (item.age_value !== null && item.age_unit !== null) {
    const template = item.age_unit === "YEARS" ? copy.ageYears : copy.ageMonths;
    parts.push(template.replace("{value}", String(item.age_value)));
  }

  return parts.join(" · ");
}
