"use client";

// CustomCohorts
//
// Owns the user-authored cohort lifecycle inside the legend: renders
// one row per authored cohort (toggle + inline "(edit)" affordance),
// renders the "+ create new" row when there's room for another, and
// drives the CohortBuilder modal. The component is array-shaped so it
// scales to multiple authored cohorts later; the underlying
// CohortBuilder still edits one cohort at a time (its draft slot lives
// in localStorage and is shared across edit sessions for now).
//
// MapView passes its current authored-cohort list down plus three
// callbacks (toggle visibility, save, delete) and stays out of the
// modal state entirely.

import { useState } from "react";
import CohortBuilder from "@/components/CohortBuilder";
import type { Cohort } from "@/lib/types";

interface Props {
  // Authored cohorts to render. Empty list = no rows; just the
  // "+ create new" affordance is shown.
  cohorts: Cohort[];
  selectedIds: Set<string>;
  onToggleSelected: (id: string) => void;
  onSave: (cohort: Omit<Cohort, "color">) => void;
  onDelete: (id: string) => void;
}

export default function CustomCohorts({
  cohorts,
  selectedIds,
  onToggleSelected,
  onSave,
  onDelete,
}: Props) {
  // Modal state lives here so MapView doesn't need to know about
  // create/edit triggers. editingId distinguishes a "new cohort" save
  // from an "edit existing" save/delete; null = creating.
  const [builderOpen, setBuilderOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const startCreate = () => {
    setEditingId(null);
    setBuilderOpen(true);
  };
  const startEdit = (id: string) => {
    setEditingId(id);
    setBuilderOpen(true);
  };

  // Builder emits `null` on delete, otherwise the saved cohort. In
  // create mode there is no id to delete; the modal disables the
  // delete button in that case so this branch is defensive.
  const handleCohort = (c: Omit<Cohort, "color"> | null) => {
    if (c === null) {
      if (editingId) onDelete(editingId);
    } else {
      onSave(c);
    }
    setBuilderOpen(false);
    setEditingId(null);
  };

  return (
    <>
      {cohorts.map((c) => {
        const selected = selectedIds.has(c.id);
        return (
          <div
            key={c.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "2px 0",
              lineHeight: 1.3,
            }}
          >
            <button
              type="button"
              onClick={() => onToggleSelected(c.id)}
              title={selected ? "hide cohort" : "show cohort"}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                background: "transparent",
                border: "none",
                padding: 0,
                textAlign: "left",
                cursor: "pointer",
                font: "inherit",
                color: selected ? "#1a1f2e" : "#9ca3af",
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 5,
                  background: selected ? c.color : "transparent",
                  border: selected ? "none" : `2px solid ${c.color}`,
                  flexShrink: 0,
                  boxSizing: "border-box",
                  opacity: selected ? 1 : 0.55,
                }}
              />
              <span style={{ opacity: selected ? 1 : 0.7 }}>{c.name}</span>
            </button>
            <button
              type="button"
              onClick={() => startEdit(c.id)}
              title="edit your cohort"
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                cursor: "pointer",
                fontSize: 12,
                fontFamily: "ui-monospace, monospace",
                color: "#6a7283",
                flexShrink: 0,
              }}
            >
              (edit)
            </button>
          </div>
        );
      })}
      {cohorts.length === 0 && (
        <button
          type="button"
          onClick={startCreate}
          title="create a new cohort"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 0 2px",
            marginTop: 4,
            borderTop: "1px solid rgba(0,0,0,0.06)",
            lineHeight: 1.3,
            background: "transparent",
            border: "none",
            borderTopWidth: 1,
            textAlign: "left",
            cursor: "pointer",
            font: "inherit",
            color: "#6a7283",
            width: "100%",
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 5,
              border: "1px dashed #9ca3af",
              flexShrink: 0,
              boxSizing: "border-box",
            }}
          />
          <span>+ create new</span>
        </button>
      )}
      <CohortBuilder
        onCohort={handleCohort}
        hasCohort={editingId !== null}
        open={builderOpen}
        onOpenChange={setBuilderOpen}
      />
    </>
  );
}
