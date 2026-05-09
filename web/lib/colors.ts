// Single source of truth for subculture colors. Imported by MapView, Sidebar,
// and the mobile legend in page.tsx.

export const COLORS: Record<string, string> = {
  queer_leftist: "#0d9488",          // teal-600 (was royal blue, now more teal)
  married_gays: "#a78bfa",           // lavender (was fuchsia, now softer purple)
  bilingual_baddie: "#f97316",       // orange-500
  crumbl_cookie_couple: "#ec4899",   // pink-500
  hill_people: "#355E3B",            // hunter green
  redneck: "#7F1D1D",                // dark flag red
};

export const FALLBACK_COLOR = "#7eaaff";
