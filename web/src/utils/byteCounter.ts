export function getByteLength(str: string): number {
  return new TextEncoder().encode(str).length;
}

export function getCharLength(str: string): number {
  return str.length;
}
