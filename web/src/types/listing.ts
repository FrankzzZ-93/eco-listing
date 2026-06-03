export interface ListingData {
  title: string;
  bullet_points: string[];
  description: string;
}

export interface WordFrequencyReport {
  total_keywords: number;
  used_in_listing: number;
  added_to_st: number;
  total_bytes: number;
}

export interface FinalDownloadLinks {
  json: string;
  markdown: string;
}

// Mirrors GET /api/runs/{run_id}/final.
// Note: the backend currently doesn't emit `verification` / `product_name` /
// `site`, so they're intentionally absent from this type.
export interface FinalOutput {
  final_listing: ListingData;
  final_st: string[];
  word_frequency_report?: WordFrequencyReport;
  download?: FinalDownloadLinks;
}
