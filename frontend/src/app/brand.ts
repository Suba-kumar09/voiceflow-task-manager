/** Branding is configurable (VITE_APP_NAME); never hard-code the product name elsewhere. */
export const brand = {
  name: import.meta.env.VITE_APP_NAME ?? 'VoiceFlow',
  tagline: 'Agentic Task Management',
} as const
