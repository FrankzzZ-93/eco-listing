export interface ListingData {
  title: string;
  bullet_points: string[];
  description: string;
  search_terms: string;
}

export interface VerificationItem {
  label: string;
  passed: boolean;
  detail: string;
}

export interface FinalOutput {
  listing: ListingData;
  verification: VerificationItem[];
  product_name?: string;
  site: string;
}
