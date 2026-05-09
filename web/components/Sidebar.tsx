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
  isMobile?: boolean;
  open?: boolean;
}

export default function Sidebar({
  subcultures,
  selected,
  onToggle,
  scores,
  isMobile = false,
  open = true,
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
        flexShrink: 0,
        ...(isMobile
          ? {
              position: "fixed",
              left: 0,
              top: 0,
              height: "100%",
              zIndex: 20,
              transform: open ? "translateX(0)" : "translateX(-100%)",
              transition: "transform 250ms ease",
              boxShadow: open ? "2px 0 12px rgba(0,0,0,0.08)" : "none",
            }
          : {}),
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

      <div
        style={{
          marginTop: 24,
          paddingTop: 16,
          borderTop: "1px solid #e5e7eb",
          fontSize: 11,
          color: "#6b7280",
        }}
      >
        <a
          href="https://github.com/djbusstop/real-californians-map"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: "#6b7280",
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
          onMouseOver={(e) => (e.currentTarget.style.color = "#1a1f2e")}
          onMouseOut={(e) => (e.currentTarget.style.color = "#6b7280")}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-1.93c-3.2.69-3.87-1.54-3.87-1.54-.52-1.33-1.27-1.69-1.27-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.69 1.24 3.35.95.1-.74.4-1.24.72-1.52-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.18-3.1-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.18a10.95 10.95 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.58.23 2.75.11 3.04.74.81 1.18 1.84 1.18 3.1 0 4.42-2.69 5.4-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.66.79.55 4.57-1.52 7.86-5.83 7.86-10.91C23.5 5.65 18.35.5 12 .5z" />
          </svg>
          View on GitHub
        </a>
      </div>
    </aside>
  );
}
