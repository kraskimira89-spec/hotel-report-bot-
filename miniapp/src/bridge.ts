import { MaxWebApp, MaxWebAppInitDataUnsafe } from "./max-bridge";

/** Доступ к MAX Bridge; вне MAX — заглушка для локальной разработки. */
export function getWebApp(): MaxWebApp {
  if (typeof window !== "undefined" && window.WebApp) {
    return window.WebApp;
  }
  return {
    initData: "",
    initDataUnsafe: {},
    platform: "web",
    version: "dev",
  };
}

export function getInitDataUnsafe(): MaxWebAppInitDataUnsafe {
  return getWebApp().initDataUnsafe ?? {};
}

export function getPlatform(): string {
  return getWebApp().platform ?? "web";
}
