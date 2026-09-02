/**
 * Content normalization for Memory records.
 *
 * "Normalized content" is the canonical text of a record: Unicode NFC,
 * whitespace collapsed to single spaces, trimmed. The content hash is
 * computed over the normalized form so duplicate detection and integrity
 * checks are stable across clients.
 */

export function normalizeText(input: string): string {
  return input.normalize("NFC").replace(/\s+/g, " ").trim();
}
