const ASIN_REGEX = /^B0[A-Z0-9]{8}$/;

export function isValidAsin(value: string): boolean {
  return ASIN_REGEX.test(value.trim().toUpperCase());
}

export function normalizeAsin(value: string): string {
  return value.trim().toUpperCase();
}
