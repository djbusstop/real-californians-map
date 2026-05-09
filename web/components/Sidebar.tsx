"use client";

import type { Scores, Subculture } from "@/app/page";

const COLORS: Record<string, string> = {
  queer_leftist: "#2563eb",
  married_gays: "#d946ef",
  bilingual_baddie: "#f97316",
  crumbl_cookie_couple: "#ec4899",
  wino: "#722f37",
  hill_people: "#355E3B",
  stupid_guy: "#8b6f47",
};

interface Props {
  subcultures: Subculture[];
  selected: string[];
  onToggle: (id: string) => void;
  scores: Scores | null;
}

export default function Sidebar({
  subcultures,
  selected,
  onToggle,
  scores,
}: Props) {
  const stats = scores
    ? subcultures.map((s) => {
        let total = 0;
        for (const vals of Object.values(scores)) total += vals[s.id] ?? 0;
        return { id: s.id, total };
      })
    : null;
  const getStat = (id: string) => stats?.find((s) => s.id === id);

  return (
    <aside
      style={{
        width: 320,
        background: "#ffffff",
        borderRight: "1px solid #e5e7eb",
        padding: "20px 18px",
        overflowY: "auto",
        color: "#1a1f2e",
      }}
    >
      <h1
        style={{ margin: "0 0 12px", lineHeight: 1.05, width: "max-content" }}
      >
        <span
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 600,
            color: "#075985" /* darker California sky blue */,
            textTransform: "uppercase",
            letterSpacing: 2,
          }}
        >
          where
        </span>
        <span
          style={{
            display: "block",
            fontFamily: 'Georgia, "Times New Roman", serif',
            fontSize: 30,
            fontWeight: 700,
            letterSpacing: -0.5,
            color: "#FB8500" /* California poppy orange */,
            margin: "2px 0",
          }}
        >
          Real Californians
        </span>
        <span
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 600,
            color: "#15803D" /* darker California green */,
            textTransform: "uppercase",
            letterSpacing: 2,
            textAlign: "right",
          }}
        >
          live
        </span>
      </h1>

      <p style={{ color: "#6b7280", fontSize: 11, margin: "0 0 20px" }}>
        {selected.length} selected
        {selected.length > 0 && (
          <button
            onClick={() => selected.forEach((id) => onToggle(id))}
            style={{
              marginLeft: 8,
              background: "none",
              border: "none",
              color: "#0EA5E9",
              fontSize: 11,
              cursor: "pointer",
              textDecoration: "underline",
              padding: 0,
            }}
          >
            clear
          </button>
        )}
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {subcultures.map((s) => {
          const stat = getStat(s.id);
          const isSelected = selected.includes(s.id);
          const accent = COLORS[s.id] ?? "#7eaaff";
          return (
            <button
              key={s.id}
              onClick={() => onToggle(s.id)}
              style={{
                textAlign: "left",
                padding: "14px 16px",
                border: "1px solid",
                borderColor: isSelected ? accent : "#e5e7eb",
                background: isSelected ? `${accent}15` : "transparent",
                borderRadius: 6,
                color: "#1a1f2e",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 13,
                lineHeight: 1.4,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                }}
              >
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: isSelected ? accent : "#d1d5db",
                    flexShrink: 0,
                  }}
                />
              </div>
              <div style={{ color: "#6b7280", fontSize: 11, marginTop: 2 }}>
                {s.vibe}
              </div>
              <div
                style={{
                  color: isSelected ? accent : "#9ca3af",
                  fontSize: 10,
                  marginTop: 6,
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                {stat ? (
                  `total ${Math.round(stat.total).toLocaleString()}`
                ) : (
                  <span
                    style={{
                      display: "inline-block",
                      width: 80,
                      height: 10,
                      borderRadius: 3,
                      background: "#e5e7eb",
                    }}
                  />
                )}
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
