/** Типы MAX Bridge (window.WebApp). См. https://dev.max.ru/docs/webapps/bridge */

export interface MaxWebAppUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  photo_url?: string;
}

export interface MaxWebAppChat {
  id: number;
  type: "DIALOG" | "CHAT" | "CHANNEL";
}

export interface MaxWebAppInitDataUnsafe {
  query_id?: string;
  ip?: string;
  auth_date?: number;
  hash?: string;
  user?: MaxWebAppUser;
  chat?: MaxWebAppChat;
  start_param?: string;
}

export interface MaxWebApp {
  initData: string;
  initDataUnsafe: MaxWebAppInitDataUnsafe;
  platform: "ios" | "android" | "desktop" | "web" | string;
  version: string;
  ready?: () => void;
  close?: () => void;
  openLink?: (url: string) => void;
  openMaxLink?: (url: string) => void;
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
  }
}

export {};
