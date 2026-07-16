/* KCR shared theme engine.
   Modes: auto (follows real sunrise/sunset at Kingsclear) · light · dark.
   Also exposes setMood() so daytime colors shift with the weather. */
"use strict";

window.KCRTheme = (function () {
  const HOME = { lat: 45.9636, lon: -66.6431 };
  let button = null;
  let onChange = null;

  function solarTimes(date) {
    const rad = Math.PI / 180, lat = HOME.lat, lon = HOME.lon;
    const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 864e5);
    const gamma = (2 * Math.PI / 365) * (dayOfYear - 1 + (date.getHours() - 12) / 24);
    const eqTime = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
      - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma));
    const decl = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
      - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma)
      - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma);
    const haCos = (Math.cos(90.833 * rad) / (Math.cos(lat * rad) * Math.cos(decl))) - Math.tan(lat * rad) * Math.tan(decl);
    if (haCos < -1 || haCos > 1) return null;
    const ha = Math.acos(haCos) / rad;
    const noon = 720 - 4 * lon - eqTime;
    const offset = -date.getTimezoneOffset();
    const sunrise = new Date(date); sunrise.setHours(0, 0, 0, 0); sunrise.setMinutes(noon - ha * 4 + offset);
    const sunset = new Date(date); sunset.setHours(0, 0, 0, 0); sunset.setMinutes(noon + ha * 4 + offset);
    return { sunrise, sunset };
  }

  const mode = () => localStorage.getItem("kcr-theme-mode") || "auto";

  function autoTheme() {
    const now = new Date();
    const sun = solarTimes(now);
    const day = sun ? now >= sun.sunrise && now < sun.sunset : (now.getHours() >= 6 && now.getHours() < 21);
    return day ? "light" : "dark";
  }

  function currentTheme() {
    const m = mode();
    return m === "auto" ? autoTheme() : m;
  }

  function updateButton() {
    if (!button) return;
    const labels = { auto: "◎", light: "☀", dark: "☾" };
    button.textContent = labels[mode()];
    button.title = { auto: "Theme: auto (sun-driven) — tap to change", light: "Theme: day — tap to change", dark: "Theme: night — tap to change" }[mode()];
  }

  function apply() {
    const theme = currentTheme();
    const previous = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("kcr-theme-applied", theme); // fast boot paint
    updateButton();
    if (previous !== theme && onChange) onChange(theme);
  }

  function cycle() {
    const order = ["auto", "light", "dark"];
    const next = order[(order.indexOf(mode()) + 1) % order.length];
    localStorage.setItem("kcr-theme-mode", next);
    apply();
    if (onChange) onChange(currentTheme());
  }

  function bind(toggleButton, changeCallback) {
    button = toggleButton;
    onChange = changeCallback || null;
    button.onclick = cycle;
    apply();
    // Re-evaluate every minute so the page flips at actual sunset/sunrise.
    setInterval(apply, 60000);
  }

  function setMood(mood) {
    document.documentElement.setAttribute("data-mood", mood || "clear");
  }

  return { bind, apply, setMood, currentTheme };
})();
