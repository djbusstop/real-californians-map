"use client";

import type { Scores, Subculture } from "@/app/page";

const COLORS: Record<string, string> = {
  queer_leftist: "#2563eb",
  bilingual_baddie: "#f97316",
  crumbl_cookie_couple: "#ec4899",
  wino: "#722f37",
  hill_people: "#6b6e1f",
  stupid_guy: "#8b6f47",
};

interface Props {
  subcultures: Subculture[];
  selected: string[];
  onToggle: (id: string) => void;
  scores: Scores | null;
}

export default function Sidebar({ subcultures, selected, onToggle, scores }: Props) {
  const stats = scores
    ? subcultures.map((s) => {
        const vals = Object.values(scores).map((p) => p[s.id] ?? 0);
        const total = vals.reduce((a, b) => a + b, 0);
        const peak = Math.max(...vals, 0);
        return { id: s.id, total, peak };
      })
    : [];
  const getStat = (id: string) => stats.find((s) => s.id === id);

  return (
    <aside
      style={{
        width: 320,
        background: "#0f1116",
        borderRight: "1px solid #1f2330",
        padding: "20px 18px",
        overflowY: "auto",
      }}
    >
      <h1 style={{ margin: "0 0 12px", lineHeight: 1.05 }}>
        <span
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 400,
            color: "#7d8499",
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
            color: "#e8eaed",
            margin: "2px 0",
          }}
        >
          Real Californians
        </span>
        <span
          style={{
            display: "block",
            fontSize: 11,
            fontWeight: 400,
            color: "#7d8499",
            textTransform: "uppercase",
            letterSpacing: 2,
            textAlign: "right",
          }}
        >
          live
        </span>
      </h1>
      <p style={{ color: "#7d8499", fontSize: 12, margin: "0 0 8px" }}>
        Subculture proxies on CA tracts. Toggle multiple to overlay.
      </p>
      <p style={{ color: "#5d6378", fontSize: 11, margin: "0 0 20px" }}>
        {selected.length} selected
        {selected.length > 0 && (
          <button
            onClick={() => selected.forEach((id) => onToggle(id))}
            style={{
              marginLeft: 8,
              background: "none",
              border: "none",
              color: "#5d6378",
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
                padding: "10px 12px",
                border: "1px solid",
                borderColor: isSelected ? accent : "transparent",
                background: isSelected ? "#1a1f2e" : "transparent",
                borderRadius: 6,
                color: "inherit",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 13,
                lineHeight: 1.4,
                position: "relative",
                paddingLeft: 18,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: 8,
                  top: 14,
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  background: isSelected ? accent : "#2a3041",
                }}
              />
              <div style={{ fontWeight: 500 }}>{s.name}</div>
              <div style={{ color: "#7d8499", fontSize: 11, marginTop: 2 }}>
                {s.vibe}
              </div>
              {stat && (
                <div
                  style={{
                    color: isSelected ? accent : "#5d6378",
                    fontSize: 10,
                    marginTop: 6,
                    fontFamily: "ui-monospace, monospace",
                  }}
                >
                  total {Math.round(stat.total).toLocaleString()} · peak{" "}
                  {Math.round(stat.peak).toLocaleString()}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </aside>
  );
}
