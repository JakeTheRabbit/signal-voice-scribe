import type { Theme } from "./types";
export function resolveTheme(
  value: Theme,
  dark = matchMedia("(prefers-color-scheme: dark)").matches,
) {
  return value === "system" ? (dark ? "dark" : "light") : value;
}
export function applyTheme(value: Theme) {
  const media = matchMedia("(prefers-color-scheme: dark)");
  const update = () => {
    const dark = resolveTheme(value, media.matches) === "dark";
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  };
  update();
  media.addEventListener("change", update);
  return () => media.removeEventListener("change", update);
}
