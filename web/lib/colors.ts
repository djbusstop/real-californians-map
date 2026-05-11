// Single source of truth for subculture colors. Imported by MapView, Sidebar,
// and the mobile legend in page.tsx.

export const COLORS: Record<string, string> = {
  queer_leftist: "#0d9488", // teal-600 (was royal blue, now more teal)
  married_gays: "#a78bfa", // lavender (was fuchsia, now softer purple)
  bilingual_baddie: "#f97316", // orange-500
  crumbl_cookie_couple: "#ec4899", // pink-500
  hill_people: "#15803D", // green-700, clearly green at dot scale
  crazy_person: "#2e3745", // slate-600, somber concrete
  teen_boy: "#2563eb", // blue-600, confident-suburban-boy blue
  younger_sister: "#d946ef", // fuchsia-500, distinct from crumbl pink and married_gays lavender
};

export const FALLBACK_COLOR = "#7eaaff";
